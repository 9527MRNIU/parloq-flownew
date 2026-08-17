"""add encrypted system platform credentials

Revision ID: 0038_system_configuration
Revises: 0037_pairing_rate_defaults
Create Date: 2026-08-17
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0038_system_configuration"
down_revision = "0037_pairing_rate_defaults"
branch_labels = None
depends_on = None

EPOCH_MS = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
MIGRATION_NODE_ID = 1023


def _id_tables(connection: sa.Connection) -> tuple[str, ...]:
    inspector = sa.inspect(connection)
    return tuple(
        table
        for table in inspector.get_table_names()
        if any(column["name"] == "id" for column in inspector.get_columns(table))
    )


def _next_snowflake_id(
    connection: sa.Connection,
    id_tables: tuple[str, ...],
    *,
    offset: int,
) -> int:
    timestamp_ms = max(int(datetime.now(UTC).timestamp() * 1000), EPOCH_MS)
    while True:
        candidate = (
            ((timestamp_ms + offset // 4096 - EPOCH_MS) << 22)
            | (MIGRATION_NODE_ID << 12)
            | (offset % 4096)
        )
        if not any(
            connection.execute(
                sa.text(f'SELECT 1 FROM "{table}" WHERE id = :id LIMIT 1'),
                {"id": candidate},
            ).first()
            for table in id_tables
        ):
            return candidate
        offset += 1


def upgrade() -> None:
    op.create_table(
        "system_credentials",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("credential_key", sa.String(length=64), nullable=False),
        sa.Column("value_ciphertext", sa.Text(), nullable=False),
        sa.Column("value_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("value_last4", sa.String(length=4), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_key",
            "credential_key",
            name="uq_system_credentials_platform_credential",
        ),
    )
    op.create_index(
        "ix_system_credentials_platform_key",
        "system_credentials",
        ["platform_key"],
    )
    op.create_index(
        "ix_system_credentials_value_fingerprint",
        "system_credentials",
        ["value_fingerprint"],
    )
    op.create_index(
        "ix_system_credentials_updated_by",
        "system_credentials",
        ["updated_by"],
    )

    connection = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", sa.MetaData(), autoload_with=connection
    )
    system_id = connection.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_system")
    ).scalar_one()
    temporary_sort_order = (
        connection.execute(
            sa.select(sa.func.max(menus.c.sort_order)).where(
                menus.c.parent_id == system_id
            )
        ).scalar_one_or_none()
        or 0
    )
    # Some deployed databases retain a legacy unique constraint on sibling
    # sort orders. Move both existing rows out of the target range before
    # inserting/reordering so every intermediate statement remains valid.
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_developer_docs")
        .values(sort_order=temporary_sort_order + 1)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_menus")
        .values(sort_order=temporary_sort_order + 2)
    )
    id_tables = _id_tables(connection)
    menu_id = _next_snowflake_id(connection, id_tables, offset=0)
    connection.execute(
        menus.insert().values(
            id=menu_id,
            public_id="menu_system_configuration",
            parent_id=system_id,
            name="系统配置",
            menu_type="page",
            route_path="/system/configuration",
            icon="KeyRound",
            permission_key="system.configuration.manage",
            sort_order=904,
            enabled=True,
            visible=True,
            is_builtin=True,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_developer_docs")
        .values(sort_order=903)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_menus")
        .values(sort_order=905)
    )

    admin_role_id = connection.execute(
        sa.select(roles.c.id).where(roles.c.system_key == "admin")
    ).scalar_one_or_none()
    if admin_role_id is not None:
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=1),
                role_id=admin_role_id,
                menu_id=menu_id,
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    menu_id = connection.execute(
        sa.text(
            "SELECT id FROM system_menus "
            "WHERE public_id = 'menu_system_configuration'"
        )
    ).scalar_one_or_none()
    if menu_id is not None:
        connection.execute(
            sa.text("DELETE FROM role_menu_permissions WHERE menu_id = :menu_id"),
            {"menu_id": menu_id},
        )
        connection.execute(
            sa.text("DELETE FROM system_menus WHERE id = :menu_id"),
            {"menu_id": menu_id},
        )
    system_id = connection.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_system")
    ).scalar_one()
    temporary_sort_order = (
        connection.execute(
            sa.select(sa.func.max(menus.c.sort_order)).where(
                menus.c.parent_id == system_id
            )
        ).scalar_one_or_none()
        or 0
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_developer_docs")
        .values(sort_order=temporary_sort_order + 1)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_system_menus")
        .values(sort_order=temporary_sort_order + 2)
    )
    connection.execute(
        sa.text(
            "UPDATE system_menus SET sort_order = 903 "
            "WHERE public_id = 'menu_system_menus'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE system_menus SET sort_order = 904 "
            "WHERE public_id = 'menu_system_developer_docs'"
        )
    )
    op.drop_index("ix_system_credentials_updated_by", table_name="system_credentials")
    op.drop_index(
        "ix_system_credentials_value_fingerprint", table_name="system_credentials"
    )
    op.drop_index(
        "ix_system_credentials_platform_key", table_name="system_credentials"
    )
    op.drop_table("system_credentials")
