"""repair pairing intake navigation for existing installations

Revision ID: 0044_pairing_observability
Revises: 0043_meta_domain_monitoring
Create Date: 2026-08-18
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0044_pairing_observability"
down_revision = "0043_meta_domain_monitoring"
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
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=connection)
    role_menus = sa.Table(
        "role_menu_permissions", sa.MetaData(), autoload_with=connection
    )
    account_center_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_account_center"
        )
    ).scalar_one()
    id_tables = _id_tables(connection)
    menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_account_intake"
        )
    ).scalar_one_or_none()
    if menu_id is None:
        connection.execute(
            menus.update()
            .where(menus.c.public_id == "menu_resources_accounts_export")
            .values(sort_order=315)
        )
    if menu_id is None:
        menu_id = _next_snowflake_id(connection, id_tables, offset=0)
        connection.execute(
            menus.insert().values(
                id=menu_id,
                public_id="menu_resources_account_intake",
                parent_id=account_center_id,
                name="接入记录",
                menu_type="page",
                route_path="/resources/accounts/intake",
                permission_key="resources.account_intake.read",
                sort_order=314,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )
    else:
        connection.execute(
            menus.update()
            .where(menus.c.id == menu_id)
            .values(
                parent_id=account_center_id,
                name="接入记录",
                menu_type="page",
                route_path="/resources/accounts/intake",
                permission_key="resources.account_intake.read",
                sort_order=314,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )

    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_accounts_export")
        .values(sort_order=315)
    )
    offset = 1
    role_ids = connection.execute(
        sa.select(roles.c.id).where(
            roles.c.system_key.in_(("admin", "operator"))
        )
    ).scalars()
    for role_id in role_ids:
        exists = connection.execute(
            sa.select(role_menus.c.id).where(
                role_menus.c.role_id == role_id,
                role_menus.c.menu_id == menu_id,
            )
        ).first()
        if exists:
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
    # This is a forward data repair for a menu that 0034 already owns. Removing
    # it during downgrade would also remove correctly seeded 0034 installations.
    pass
