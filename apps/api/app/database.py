from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(Engine, "connect")
    def _sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db


def seed_initial_data(db: Session) -> None:
    from app.models import (
        BitlyProviderAccount,
        RoleActionPermission,
        RoleMenuPermission,
        SystemMenu,
        UserAccount,
        UserGroup,
    )
    from app.security import encrypt_secret, hash_password, secret_fingerprint
    from app.snowflake import new_public_id

    admin_group = db.scalar(select(UserGroup).where(UserGroup.system_key == "admin"))
    if admin_group is None:
        admin_group = UserGroup(
            name="管理员",
            system_key="admin",
            description="系统内置管理员组",
            is_builtin=True,
        )
        db.add(admin_group)
        db.flush()

    operator_group = db.scalar(select(UserGroup).where(UserGroup.system_key == "operator"))
    if operator_group is None:
        operator_group = UserGroup(
            name="普通用户",
            system_key="operator",
            description="系统内置普通用户组",
            is_builtin=True,
        )
        db.add(operator_group)
        db.flush()

    all_menus = db.scalars(select(SystemMenu)).all()
    assigned_admin = {permission.menu_id for permission in admin_group.menu_permissions}
    assigned_operator = {permission.menu_id for permission in operator_group.menu_permissions}
    for menu in all_menus:
        if menu.id not in assigned_admin:
            admin_group.menu_permissions.append(RoleMenuPermission(menu_id=menu.id))
        operator_menu = (
            menu.public_id == "menu_resources"
            or menu.public_id in {
                "menu_resources_operations",
                "menu_resources_protocol",
                "menu_resources_materials",
            }
            or menu.public_id.startswith(
                ("menu_resources_account", "menu_promotion", "menu_marketing")
            )
        )
        if operator_menu and menu.id not in assigned_operator:
            operator_group.menu_permissions.append(RoleMenuPermission(menu_id=menu.id))
    operator_actions = {
        "business.personal_accounts.manage",
        "resources.accounts.manage",
        "resources.accounts.import",
        "resources.accounts.export",
        "resources.protocol.manage",
        "promotion.templates.manage",
        "promotion.channels.manage",
        "promotion.domain.manage",
        "promotion.domain.purchase",
        "promotion.statistics.manage",
        "marketing.hyperlink_tasks.manage",
        "marketing.data_packages.manage",
        "marketing.hyperlink_templates.manage",
        "marketing.hyperlink_strategies.manage",
        "resources.materials.manage",
        "marketing.direct_short_links.manage",
    }
    admin_actions = operator_actions | {"resources.ip.manage"}
    existing_admin_actions = {
        permission.permission_key for permission in admin_group.action_permissions
    }
    existing_operator_actions = {
        permission.permission_key for permission in operator_group.action_permissions
    }
    for permission_key in admin_actions - existing_admin_actions:
        admin_group.action_permissions.append(
            RoleActionPermission(permission_key=permission_key)
        )
    for permission_key in operator_actions - existing_operator_actions:
        operator_group.action_permissions.append(
            RoleActionPermission(permission_key=permission_key)
        )

    admin = db.scalar(
        select(UserAccount).where(UserAccount.username == settings.seed_admin_username)
    )
    if admin is None:
        db.add(
            UserAccount(
                username=settings.seed_admin_username,
                display_name="Administrator",
                password_hash=hash_password(settings.seed_admin_password),
                group_id=admin_group.id,
                role="admin",
                is_active=True,
            )
        )

    if settings.bitly_mock:
        mock = db.scalar(
            select(BitlyProviderAccount).where(BitlyProviderAccount.is_mock.is_(True))
        )
        if mock is None:
            mock_token = "local-bitly-mock-token"
            db.add(
                BitlyProviderAccount(
                    public_id=new_public_id("bitly"),
                    name="Bitly Mock",
                    token_ciphertext=encrypt_secret(mock_token),
                    token_fingerprint=secret_fingerprint(mock_token),
                    token_last4="mock",
                    group_guid="mock_group",
                    short_domain="bit.ly",
                    enabled=True,
                    status="active",
                    is_mock=True,
                )
            )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def init_database() -> None:
    if settings.auto_create_tables:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", settings.database_url)
        existing_tables = set(inspect(engine).get_table_names())
        initial_tables = {
            "user_groups",
            "user_accounts",
            "auth_sessions",
            "bitly_provider_accounts",
            "direct_short_links",
            "meta_pixels",
        }
        # Early local builds used create_all before Alembic was wired into startup.
        # Adopt that exact v1 schema, then run normal migrations without deleting data.
        if "alembic_version" not in existing_tables and initial_tables <= existing_tables:
            command.stamp(config, "0001_initial")
        command.upgrade(config, "head")
    with SessionLocal() as db:
        seed_initial_data(db)
