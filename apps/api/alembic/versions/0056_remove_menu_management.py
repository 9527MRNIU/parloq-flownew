"""remove the standalone menu-management feature

Revision ID: 0056_remove_menu_management
Revises: 0055_optional_totp_mfa
Create Date: 2026-08-21
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0056_remove_menu_management"
down_revision = "0055_optional_totp_mfa"
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
    connection = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", sa.MetaData(), autoload_with=connection
    )
    menu_id = connection.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_system_menus")
    ).scalar_one_or_none()
    if menu_id is None:
        return
    connection.execute(role_menus.delete().where(role_menus.c.menu_id == menu_id))
    connection.execute(menus.delete().where(menus.c.id == menu_id))


def downgrade() -> None:
    connection = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    if connection.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_system_menus")
    ).scalar_one_or_none() is not None:
        return

    system_id = connection.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_system")
    ).scalar_one_or_none()
    if system_id is None:
        return

    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", sa.MetaData(), autoload_with=connection
    )
    id_tables = _id_tables(connection)
    menu_id = _next_snowflake_id(connection, id_tables, offset=0)
    connection.execute(
        menus.insert().values(
            id=menu_id,
            public_id="menu_system_menus",
            parent_id=system_id,
            name="菜单管理",
            menu_type="page",
            route_path="/system/menus",
            icon="ListTree",
            permission_key="system.menus.manage",
            sort_order=905,
            enabled=True,
            visible=True,
            is_builtin=True,
        )
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
