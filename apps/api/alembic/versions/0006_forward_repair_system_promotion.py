"""Forward-repair early 0005 deployments without deleting user data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision: str = "0006_forward_repair"
down_revision: str | None = "0005_system_promotion_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {
        index["name"] for index in inspector.get_indexes(table)
    } | {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table)
        if constraint.get("name")
    }


def _add_column(bind, table: str, column: sa.Column) -> None:
    if column.name not in _columns(bind, table):
        op.add_column(table, column)


def _create_index(bind, name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(bind, table):
        op.create_index(name, table, columns, unique=unique)


def _repair_columns_and_tables(bind) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    _add_column(
        bind,
        "user_groups",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _create_index(bind, "ix_user_groups_enabled", "user_groups", ["enabled"])
    _add_column(bind, "promotion_events", sa.Column("visitor_id", sa.String(80)))
    _create_index(
        bind,
        "ix_promotion_events_channel_visitor",
        "promotion_events",
        ["channel_id", "visitor_id"],
    )
    _add_column(
        bind,
        "ad_metrics",
        sa.Column("other_cost", sa.Numeric(18, 6), nullable=False, server_default="0"),
    )

    domain_columns = (
        sa.Column("acquisition_type", sa.String(16), nullable=False, server_default="connected"),
        sa.Column("management_mode", sa.String(16), nullable=False, server_default="external"),
        sa.Column("registrar_provider", sa.String(80)),
        sa.Column("registration_status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hosting_provider", sa.String(80), nullable=False, server_default="cloudflare"),
        sa.Column("hosting_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("verification_token", sa.String(80)),
    )
    for column in domain_columns:
        _add_column(bind, "domains", column)
    for column in (
        "acquisition_type",
        "management_mode",
        "registration_status",
        "expires_at",
        "hosting_status",
    ):
        _create_index(bind, f"ix_domains_{column}", "domains", [column])

    domains = sa.Table("domains", sa.MetaData(), autoload_with=bind)
    for domain_id, dns_status, ssl_status, token in bind.execute(
        sa.select(domains.c.id, domains.c.dns_status, domains.c.ssl_status, domains.c.verification_token)
    ):
        values: dict[str, object] = {}
        if not token:
            values["verification_token"] = f"legacy-domain-{domain_id}"
        if dns_status == "verified" and ssl_status == "verified":
            values["hosting_status"] = "active"
            values["registration_status"] = "active"
        if values:
            bind.execute(domains.update().where(domains.c.id == domain_id).values(**values))
    _create_index(
        bind,
        "uq_domains_verification_token",
        "domains",
        ["verification_token"],
        unique=True,
    )
    if bind.dialect.name != "sqlite":
        verification_column = next(
            column
            for column in sa.inspect(bind).get_columns("domains")
            if column["name"] == "verification_token"
        )
        if verification_column.get("nullable", True):
            op.alter_column(
                "domains",
                "verification_token",
                existing_type=sa.String(80),
                nullable=False,
            )
        domain_checks = {
            constraint["name"]
            for constraint in sa.inspect(bind).get_check_constraints("domains")
        }
        for name, condition in (
            ("ck_domains_acquisition_type", "acquisition_type IN ('connected', 'purchased')"),
            ("ck_domains_management_mode", "management_mode IN ('external', 'platform')"),
            ("ck_domains_registration_status", "registration_status IN ('active', 'pending', 'failed', 'expired')"),
            ("ck_domains_hosting_status", "hosting_status IN ('pending', 'active', 'failed')"),
        ):
            if name not in domain_checks:
                op.create_check_constraint(name, "domains", condition)

    if "domain_quotes" not in tables:
        op.create_table(
            "domain_quotes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(64), nullable=False, unique=True),
            sa.Column("hostname", sa.String(255), nullable=False),
            sa.Column("years", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False),
            *_timestamps(),
        )
    for column in ("public_id", "hostname", "expires_at", "created_by"):
        _create_index(bind, f"ix_domain_quotes_{column}", "domain_quotes", [column])

    if "domain_orders" not in tables:
        op.create_table(
            "domain_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(64), nullable=False, unique=True),
            sa.Column("quote_id", sa.Integer(), sa.ForeignKey("domain_quotes.id", ondelete="RESTRICT"), nullable=False, unique=True),
            sa.Column("hostname", sa.String(255), nullable=False),
            sa.Column("years", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending_payment"),
            sa.Column("provider", sa.String(80), nullable=False, server_default="mock"),
            sa.Column("provider_order_ref", sa.String(160), unique=True),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("failure_reason", sa.Text()),
            sa.Column("paid_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
            sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="SET NULL"), unique=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
                name="ck_domain_orders_status",
            ),
            sa.CheckConstraint("years >= 1 AND years <= 10", name="ck_domain_orders_years"),
            sa.CheckConstraint("amount >= 0", name="ck_domain_orders_amount"),
            *_timestamps(),
        )
    else:
        _add_column(bind, "domain_orders", sa.Column("quote_id", sa.Integer()))
        _add_column(bind, "domain_orders", sa.Column("last_reconciled_at", sa.DateTime(timezone=True)))

    quotes = sa.Table("domain_quotes", sa.MetaData(), autoload_with=bind)
    orders = sa.Table("domain_orders", sa.MetaData(), autoload_with=bind)
    if "quote_id" in orders.c:
        for order in bind.execute(sa.select(orders)).mappings():
            if order.get("quote_id") is not None:
                continue
            public_id = f"legacy_quote_{order['id']}"
            quote_id = bind.execute(
                sa.select(quotes.c.id).where(quotes.c.public_id == public_id)
            ).scalar_one_or_none()
            if quote_id is None:
                created_at = order.get("created_at") or datetime.now(UTC)
                result = bind.execute(
                    quotes.insert().values(
                        public_id=public_id,
                        hostname=order["hostname"],
                        years=order.get("years") or 1,
                        amount=order.get("amount") or 0,
                        currency=order.get("currency") or "USD",
                        provider=order.get("provider") or "legacy",
                        expires_at=created_at,
                        consumed_at=created_at,
                        created_by=order["created_by"],
                    )
                )
                quote_id = result.inserted_primary_key[0]
            bind.execute(orders.update().where(orders.c.id == order["id"]).values(quote_id=quote_id))
        _create_index(bind, "ix_domain_orders_quote_id", "domain_orders", ["quote_id"], unique=True)
    for column in ("public_id", "hostname", "status", "domain_id", "created_by"):
        if column in orders.c:
            _create_index(bind, f"ix_domain_orders_{column}", "domain_orders", [column])

    order_inspector = sa.inspect(bind)
    status_checks = [
        constraint
        for constraint in order_inspector.get_check_constraints("domain_orders")
        if "status" in str(constraint.get("sqltext", "")).lower()
    ]
    for constraint in status_checks:
        if "unknown" in str(constraint.get("sqltext", "")).lower():
            continue
        name = constraint.get("name")
        if name:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("domain_orders") as batch:
                    batch.drop_constraint(name, type_="check")
                    batch.create_check_constraint(
                        "ck_domain_orders_status",
                        "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
                    )
            else:
                op.drop_constraint(name, "domain_orders", type_="check")
                op.create_check_constraint(
                    "ck_domain_orders_status",
                    "domain_orders",
                    "status IN ('pending_payment', 'paid', 'provisioning', 'unknown', 'completed', 'failed', 'cancelled')",
                )
        break

    if bind.dialect.name != "sqlite":
        quote_column = next(
            column
            for column in sa.inspect(bind).get_columns("domain_orders")
            if column["name"] == "quote_id"
        )
        if quote_column.get("nullable", True):
            op.alter_column(
                "domain_orders",
                "quote_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
        quote_fks = {
            tuple(constraint.get("constrained_columns") or ())
            for constraint in sa.inspect(bind).get_foreign_keys("domain_orders")
        }
        if ("quote_id",) not in quote_fks:
            op.create_foreign_key(
                "fk_domain_orders_quote_id_domain_quotes",
                "domain_orders",
                "domain_quotes",
                ["quote_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    if "role_action_permissions" not in tables:
        op.create_table(
            "role_action_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("permission_key", sa.String(120), nullable=False),
            sa.UniqueConstraint("role_id", "permission_key", name="uq_role_action_permission"),
            *_timestamps(),
        )
    _create_index(bind, "ix_role_action_permissions_role_id", "role_action_permissions", ["role_id"])
    _create_index(bind, "ix_role_action_permissions_permission_key", "role_action_permissions", ["permission_key"])


MENU_DEFINITIONS = (
    ("menu_business", None, "业务", "directory", None, "BriefcaseBusiness", None, 10),
    ("menu_business_personal_accounts", "menu_business", "个人账号", "page", "/personal-accounts", "ContactRound", "business.personal_accounts.read", 11),
    ("menu_promotion", None, "推广", "directory", None, "Megaphone", None, 100),
    ("menu_promotion_management", "menu_promotion", "推广管理", "directory", None, None, None, 110),
    ("menu_promotion_templates", "menu_promotion_management", "模板管理", "page", "/promotion/templates", "LayoutTemplate", "promotion.templates.read", 111),
    ("menu_promotion_channels", "menu_promotion_management", "渠道管理", "page", "/promotion/channels", "PanelsTopLeft", "promotion.channels.read", 112),
    ("menu_promotion_domains", "menu_promotion_management", "域名管理", "page", "/promotion/domains", "Globe2", "promotion.domain.read", 113),
    ("menu_promotion_data_center", "menu_promotion", "数据中心", "directory", None, None, None, 120),
    ("menu_promotion_statistics", "menu_promotion_data_center", "渠道统计", "page", "/promotion/statistics", "ChartNoAxesCombined", "promotion.statistics.read", 121),
    ("menu_promotion_trends", "menu_promotion_data_center", "趋势图", "page", "/promotion/trends", "ChartSpline", "promotion.trends.read", 122),
    ("menu_marketing", None, "营销", "directory", None, "Send", None, 200),
    ("menu_marketing_hyperlink", "menu_marketing", "超链营销", "directory", None, None, None, 210),
    ("menu_marketing_hyperlink_tasks", "menu_marketing_hyperlink", "超链任务", "page", "/hyperlink/tasks", None, "marketing.hyperlink_tasks.read", 211),
    ("menu_marketing_data_packages", "menu_marketing_hyperlink", "数据包", "page", "/hyperlink/data-packages", None, "marketing.data_packages.read", 212),
    ("menu_marketing_hyperlink_templates", "menu_marketing_hyperlink", "超链模板", "page", "/hyperlink/templates", None, "marketing.hyperlink_templates.read", 213),
    ("menu_marketing_hyperlink_strategies", "menu_marketing_hyperlink", "超链策略", "page", "/hyperlink/strategies", None, "marketing.hyperlink_strategies.read", 214),
    ("menu_marketing_materials", "menu_marketing_hyperlink", "素材库", "page", "/hyperlink/materials", None, "marketing.materials.read", 215),
    ("menu_marketing_insights", "menu_marketing_hyperlink", "市场透视", "page", "/hyperlink/market-insights", None, "marketing.insights.read", 216),
    ("menu_marketing_direct_short_links", "menu_marketing", "直接短链", "page", "/direct-short-links", "Link2", "marketing.direct_short_links.read", 220),
    ("menu_resources", None, "资源", "directory", None, "Blocks", None, 300),
    ("menu_resources_ip_management", "menu_resources", "IP 管理", "page", "/ip-management", "Network", "resources.ip.manage", 301),
    ("menu_system", None, "系统管理", "directory", None, "Settings", None, 900),
    ("menu_system_users", "menu_system", "用户管理", "page", "/system/users", "Users", "system.users.manage", 901),
    ("menu_system_roles", "menu_system", "角色管理", "page", "/system/roles", "ShieldCheck", "system.roles.manage", 902),
    ("menu_system_menus", "menu_system", "菜单管理", "page", "/system/menus", "ListTree", "system.menus.manage", 903),
)


OPERATOR_ACTIONS = (
    "business.personal_accounts.manage",
    "promotion.templates.manage",
    "promotion.channels.manage",
    "promotion.domain.manage",
    "promotion.domain.purchase",
    "promotion.statistics.manage",
    "marketing.hyperlink_tasks.manage",
    "marketing.data_packages.manage",
    "marketing.hyperlink_templates.manage",
    "marketing.hyperlink_strategies.manage",
    "marketing.materials.manage",
    "marketing.direct_short_links.manage",
)


def _repair_menus_and_permissions(bind) -> None:
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    role_actions = sa.Table("role_action_permissions", sa.MetaData(), autoload_with=bind)
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)
    ids: dict[str, int] = {}

    # Early 0005 used these same parent/sort slots under a uniqueness
    # constraint. Rename them in place first so IDs and role bindings survive.
    mapped_from_old: set[str] = set()
    for old_public_id, new_public_id in (
        ("menu_promotion_overview", "menu_promotion_statistics"),
        ("menu_promotion_ad_metrics", "menu_promotion_trends"),
    ):
        old_id = bind.execute(
            sa.select(menus.c.id).where(menus.c.public_id == old_public_id)
        ).scalar_one_or_none()
        new_id = bind.execute(
            sa.select(menus.c.id).where(menus.c.public_id == new_public_id)
        ).scalar_one_or_none()
        if old_id is not None and new_id is None:
            bind.execute(
                menus.update().where(menus.c.id == old_id).values(public_id=new_public_id)
            )
            mapped_from_old.add(new_public_id)

    for public_id, parent_key, name, menu_type, route, icon, permission, sort_order in MENU_DEFINITIONS:
        existing = bind.execute(
            sa.select(menus.c.id).where(menus.c.public_id == public_id)
        ).scalar_one_or_none()
        contract_values = {
            "parent_id": ids.get(parent_key) if parent_key else None,
            "menu_type": menu_type,
            "route_path": route,
            "permission_key": permission,
            "is_builtin": True,
        }
        if existing is None:
            result = bind.execute(
                menus.insert().values(
                    public_id=public_id,
                    name=name,
                    icon=icon,
                    sort_order=sort_order,
                    enabled=True,
                    visible=True,
                    **contract_values,
                )
            )
            existing = int(result.inserted_primary_key[0])
        else:
            if public_id in mapped_from_old:
                contract_values["name"] = name
            bind.execute(
                menus.update().where(menus.c.id == existing).values(**contract_values)
            )
        ids[public_id] = int(existing)

    obsolete = bind.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id.in_(["menu_promotion_overview", "menu_promotion_ad_metrics"])
        )
    ).scalars().all()
    if obsolete:
        bind.execute(role_menus.delete().where(role_menus.c.menu_id.in_(obsolete)))
        bind.execute(menus.update().where(menus.c.parent_id.in_(obsolete)).values(parent_id=None))
        bind.execute(menus.delete().where(menus.c.id.in_(obsolete)))

    role_rows = bind.execute(sa.select(roles.c.id, roles.c.system_key)).all()
    desired_menu_ids = set(ids.values())
    operator_menu_ids = {
        menu_id
        for public_id, menu_id in ids.items()
        if public_id.startswith(("menu_business", "menu_promotion", "menu_marketing"))
    }
    for role_id, system_key in role_rows:
        if system_key == "admin":
            wanted = desired_menu_ids
            actions = (*OPERATOR_ACTIONS, "resources.ip.manage")
        elif system_key == "operator":
            wanted = operator_menu_ids
            actions = OPERATOR_ACTIONS
        else:
            # Custom roles are administrator-owned policy. A repair migration
            # must never turn them into operators by granting a baseline.
            continue
        existing = set(
            bind.execute(
                sa.select(role_menus.c.menu_id).where(role_menus.c.role_id == role_id)
            ).scalars()
        )
        for menu_id in wanted - existing:
            bind.execute(role_menus.insert().values(role_id=role_id, menu_id=menu_id))
        existing_actions = set(
            bind.execute(
                sa.select(role_actions.c.permission_key).where(role_actions.c.role_id == role_id)
            ).scalars()
        )
        for permission_key in set(actions) - existing_actions:
            bind.execute(
                role_actions.insert().values(role_id=role_id, permission_key=permission_key)
            )


def upgrade() -> None:
    bind = op.get_bind()
    _repair_columns_and_tables(bind)
    _repair_menus_and_permissions(bind)


def downgrade() -> None:
    # This is an intentionally non-destructive forward repair. Reverting it
    # would remove columns needed to interpret already-created orders/domains.
    pass
