"""add promotion monitoring navigation

Revision ID: 0057_visit_monitoring
Revises: 0056_remove_menu_management
Create Date: 2026-08-23
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0057_visit_monitoring"
down_revision = "0056_remove_menu_management"
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
    roles = sa.Table("user_groups", metadata, autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", metadata, autoload_with=connection
    )
    parent_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_promotion_data_center"
        )
    ).scalar_one()
    id_tables = _id_tables(connection)

    existing = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_promotion_visit_monitoring"
        )
    ).scalar_one_or_none()
    if existing is None:
        # Move existing data-center pages out of the insertion range first so
        # installations retaining a sibling sort-order constraint stay valid.
        connection.execute(
            menus.update()
            .where(menus.c.public_id == "menu_promotion_statistics")
            .values(sort_order=1001)
        )
        connection.execute(
            menus.update()
            .where(menus.c.public_id == "menu_promotion_trends")
            .values(sort_order=1002)
        )
        menu_id = _next_snowflake_id(connection, id_tables, offset=0)
        connection.execute(
            menus.insert().values(
                id=menu_id,
                public_id="menu_promotion_visit_monitoring",
                parent_id=parent_id,
                name="访问监控",
                menu_type="page",
                route_path="/promotion/monitoring",
                icon="Activity",
                permission_key="promotion.monitoring.read",
                sort_order=121,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )
    else:
        menu_id = existing

    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_statistics")
        .values(sort_order=122)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_trends")
        .values(sort_order=123)
    )

    offset = 1
    role_ids = connection.execute(
        sa.select(roles.c.id).where(roles.c.system_key.in_(("admin", "operator")))
    ).scalars()
    for role_id in role_ids:
        if connection.execute(
            sa.select(role_menus.c.id).where(
                role_menus.c.role_id == role_id,
                role_menus.c.menu_id == menu_id,
            )
        ).first():
            continue
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=menu_id,
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
    menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_promotion_visit_monitoring"
        )
    ).scalar_one_or_none()
    if menu_id is not None:
        connection.execute(role_menus.delete().where(role_menus.c.menu_id == menu_id))
        connection.execute(menus.delete().where(menus.c.id == menu_id))
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_statistics")
        .values(sort_order=121)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_trends")
        .values(sort_order=122)
    )
