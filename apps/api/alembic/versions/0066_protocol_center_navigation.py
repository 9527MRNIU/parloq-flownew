"""combine protocol operations pages under a protocol center menu

Revision ID: 0066_protocol_center_navigation
Revises: 0065_protocol_definitions
Create Date: 2026-08-24
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0066_protocol_center_navigation"
down_revision = "0065_protocol_definitions"
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
    id_tables = _id_tables(connection)

    menu_ids = dict(
        connection.execute(
            sa.select(menus.c.public_id, menus.c.id).where(
                menus.c.public_id.in_(
                    (
                        "menu_resources_operations",
                        "menu_resources_protocol",
                        "menu_resources_protocol_definitions",
                        "menu_resources_protocol_routing",
                    )
                )
            )
        ).all()
    )
    source_menu_ids = (
        menu_ids["menu_resources_protocol"],
        menu_ids["menu_resources_protocol_definitions"],
        menu_ids["menu_resources_protocol_routing"],
    )
    role_ids = tuple(
        connection.execute(
            sa.select(role_menus.c.role_id)
            .where(role_menus.c.menu_id.in_(source_menu_ids))
            .distinct()
        ).scalars()
    )

    for public_id, temporary_order in (
        ("menu_resources_protocol", 1321),
        ("menu_resources_protocol_definitions", 1322),
        ("menu_resources_protocol_routing", 1323),
        ("menu_resources_ip_management", 1324),
    ):
        connection.execute(
            menus.update()
            .where(menus.c.public_id == public_id)
            .values(sort_order=temporary_order)
        )

    center_id = _next_snowflake_id(connection, id_tables, offset=0)
    connection.execute(
        menus.insert().values(
            id=center_id,
            public_id="menu_resources_protocol_center",
            parent_id=menu_ids["menu_resources_operations"],
            name="协议中心",
            menu_type="page",
            route_path="/resources/operations/protocol-center",
            icon=None,
            permission_key="resources.protocol_center.read",
            sort_order=321,
            enabled=True,
            visible=True,
            is_builtin=True,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.id.in_(source_menu_ids))
        .values(visible=False)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(sort_order=322)
    )

    for offset, role_id in enumerate(role_ids, start=1):
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=center_id,
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", metadata, autoload_with=connection
    )
    center_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol_center"
        )
    ).scalar_one_or_none()
    if center_id is not None:
        connection.execute(
            role_menus.delete().where(role_menus.c.menu_id == center_id)
        )
        connection.execute(menus.delete().where(menus.c.id == center_id))

    for public_id, temporary_order in (
        ("menu_resources_protocol", 1321),
        ("menu_resources_protocol_definitions", 1322),
        ("menu_resources_protocol_routing", 1323),
        ("menu_resources_ip_management", 1324),
    ):
        connection.execute(
            menus.update()
            .where(menus.c.public_id == public_id)
            .values(sort_order=temporary_order)
        )

    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol_definitions")
        .values(sort_order=321, visible=True)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol")
        .values(sort_order=322, visible=True)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol_routing")
        .values(sort_order=323, visible=True)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(sort_order=324)
    )
