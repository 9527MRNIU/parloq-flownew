"""add managed promotion runtime integrations

Revision ID: 0045_promotion_integrations
Revises: 0044_pairing_observability
Create Date: 2026-08-18
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0045_promotion_integrations"
down_revision = "0044_pairing_observability"
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
        "promotion_integrations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("integration_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("integration_type", sa.String(length=16), nullable=False),
        sa.Column("source_domain_id", sa.BigInteger(), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("integrity", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint(
            "integration_type IN ('script', 'iframe')",
            name="ck_promotion_integrations_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_domain_id"], ["domains.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by",
            "integration_key",
            name="uq_promotion_integration_owner_key",
        ),
        sa.UniqueConstraint("public_id"),
    )
    for column in (
        "public_id",
        "integration_key",
        "integration_type",
        "source_domain_id",
        "enabled",
        "archived_at",
        "created_by",
    ):
        op.create_index(
            f"ix_promotion_integrations_{column}",
            "promotion_integrations",
            [column],
        )

    op.create_table(
        "promotion_template_integrations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("integration_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
            ["template_id"], ["promotion_templates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["promotion_integrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "integration_id",
            name="uq_promotion_template_integration",
        ),
    )
    for column in ("template_id", "integration_id", "enabled"):
        op.create_index(
            f"ix_promotion_template_integrations_{column}",
            "promotion_template_integrations",
            [column],
        )

    connection = op.get_bind()
    metadata = sa.MetaData()
    menus = sa.Table("system_menus", metadata, autoload_with=connection)
    roles = sa.Table("user_groups", metadata, autoload_with=connection)
    role_menus = sa.Table("role_menu_permissions", metadata, autoload_with=connection)
    role_actions = sa.Table("role_action_permissions", metadata, autoload_with=connection)
    parent_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_promotion_management"
        )
    ).scalar_one()
    temporary_sort_order = (
        connection.execute(
            sa.select(sa.func.max(menus.c.sort_order)).where(
                menus.c.parent_id == parent_id
            )
        ).scalar_one_or_none()
        or 0
    )
    # Some deployed databases retain a legacy unique constraint on sibling
    # sort orders. Move both existing rows out of the target range first so
    # every intermediate statement remains collision-safe.
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_channels")
        .values(sort_order=temporary_sort_order + 1)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_domains")
        .values(sort_order=temporary_sort_order + 2)
    )
    id_tables = _id_tables(connection)
    menu_id = _next_snowflake_id(connection, id_tables, offset=0)
    connection.execute(
        menus.insert().values(
            id=menu_id,
            public_id="menu_promotion_integrations",
            parent_id=parent_id,
            name="集成管理",
            menu_type="page",
            route_path="/promotion/integrations",
            icon="PlugZap",
            permission_key="promotion.integrations.read",
            sort_order=112,
            enabled=True,
            visible=True,
            is_builtin=True,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_channels")
        .values(sort_order=113)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_domains")
        .values(sort_order=114)
    )

    offset = 1
    for role_key in ("admin", "operator"):
        role_id = connection.execute(
            sa.select(roles.c.id).where(roles.c.system_key == role_key)
        ).scalar_one_or_none()
        if role_id is None:
            continue
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=menu_id,
            )
        )
        offset += 1
        connection.execute(
            role_actions.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                permission_key="promotion.integrations.manage",
            )
        )
        offset += 1


def downgrade() -> None:
    connection = op.get_bind()
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=connection)
    menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_promotion_integrations"
        )
    ).scalar_one_or_none()
    connection.execute(
        sa.text(
            "DELETE FROM role_action_permissions "
            "WHERE permission_key = 'promotion.integrations.manage'"
        )
    )
    if menu_id is not None:
        connection.execute(
            sa.text("DELETE FROM role_menu_permissions WHERE menu_id = :menu_id"),
            {"menu_id": menu_id},
        )
        connection.execute(
            menus.delete().where(menus.c.id == menu_id)
        )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_channels")
        .values(sort_order=112)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_promotion_domains")
        .values(sort_order=113)
    )

    for column in ("template_id", "integration_id", "enabled"):
        op.drop_index(
            f"ix_promotion_template_integrations_{column}",
            table_name="promotion_template_integrations",
        )
    op.drop_table("promotion_template_integrations")
    for column in (
        "public_id",
        "integration_key",
        "integration_type",
        "source_domain_id",
        "enabled",
        "archived_at",
        "created_by",
    ):
        op.drop_index(
            f"ix_promotion_integrations_{column}",
            table_name="promotion_integrations",
        )
    op.drop_table("promotion_integrations")
