"""separate protocol routing navigation

Revision ID: 0063_protocol_routing_navigation
Revises: 0062_phone_country_backfill
Create Date: 2026-08-24
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0063_protocol_routing_navigation"
down_revision = "0062_phone_country_backfill"
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
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", metadata, autoload_with=connection
    )
    operations_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_operations"
        )
    ).scalar_one()
    protocol_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol"
        )
    ).scalar_one()
    id_tables = _id_tables(connection)

    # The IP menu currently occupies 322 and sibling order is unique. Move it
    # out of the insertion range before adding the routing page.
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(sort_order=1003)
    )

    routing_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol_routing"
        )
    ).scalar_one_or_none()
    if routing_id is None:
        routing_id = _next_snowflake_id(connection, id_tables, offset=0)
        connection.execute(
            menus.insert().values(
                id=routing_id,
                public_id="menu_resources_protocol_routing",
                parent_id=operations_id,
                name="路由策略",
                menu_type="page",
                route_path="/resources/operations/routing",
                icon=None,
                permission_key="resources.protocol_routing.read",
                sort_order=322,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )

    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(
            name="代理管理",
            route_path="/resources/operations/ip",
            sort_order=323,
        )
    )

    role_ids = connection.execute(
        sa.select(role_menus.c.role_id).where(role_menus.c.menu_id == protocol_id)
    ).scalars()
    offset = 1
    for role_id in role_ids:
        exists = connection.execute(
            sa.select(role_menus.c.id).where(
                role_menus.c.role_id == role_id,
                role_menus.c.menu_id == routing_id,
            )
        ).first()
        if exists:
            continue
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=routing_id,
            )
        )
        offset += 1


def downgrade() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", metadata, autoload_with=connection
    )
    routing_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol_routing"
        )
    ).scalar_one_or_none()
    if routing_id is not None:
        connection.execute(
            role_menus.delete().where(role_menus.c.menu_id == routing_id)
        )
        connection.execute(menus.delete().where(menus.c.id == routing_id))
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(name="IP 管理", sort_order=322)
    )
