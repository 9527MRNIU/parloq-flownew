"""separate protocol definitions from operational nodes

Revision ID: 0065_protocol_definitions
Revises: 0064_baileys_web_protocol_name
Create Date: 2026-08-24
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0065_protocol_definitions"
down_revision = "0064_baileys_web_protocol_name"
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
    op.create_table(
        "protocol_definitions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("adapter_key", sa.String(32), nullable=False),
        sa.Column("repository_url", sa.String(512), nullable=False),
        sa.Column("package_name", sa.String(160), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("upstream_ref", sa.String(80)),
        sa.Column(
            "build_status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "contract_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remark", sa.String(512)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "build_status IN ('pending', 'building', 'ready', 'failed', 'requires_adaptation', 'disabled')",
            name="ck_protocol_definitions_build_status",
        ),
        sa.UniqueConstraint(
            "adapter_key",
            "repository_url",
            "version",
            name="uq_protocol_definitions_source_version",
        ),
    )
    for column in (
        "public_id",
        "name",
        "adapter_key",
        "package_name",
        "version",
        "build_status",
        "enabled",
    ):
        op.create_index(
            f"ix_protocol_definitions_{column}",
            "protocol_definitions",
            [column],
        )

    id_tables = _id_tables(connection)
    definition_id = _next_snowflake_id(connection, id_tables, offset=0)
    definitions = sa.table(
        "protocol_definitions",
        sa.column("id", sa.BigInteger()),
        sa.column("public_id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("adapter_key", sa.String()),
        sa.column("repository_url", sa.String()),
        sa.column("package_name", sa.String()),
        sa.column("version", sa.String()),
        sa.column("upstream_ref", sa.String()),
        sa.column("build_status", sa.String()),
        sa.column("contract_version", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("is_builtin", sa.Boolean()),
        sa.column("remark", sa.String()),
    )
    connection.execute(
        definitions.insert().values(
            id=definition_id,
            public_id="protocol_definition_baileys_6_7_24",
            name="Baileys Web协议",
            adapter_key="baileys",
            repository_url="https://github.com/WhiskeySockets/Baileys",
            package_name="@whiskeysockets/baileys",
            version="6.7.24",
            upstream_ref="e0629940ee2d335b0c0119367fd2a934e0fa3189",
            build_status="ready",
            contract_version=1,
            enabled=True,
            is_builtin=True,
            remark="当前生产网关使用的内置 Baileys 协议定义",
        )
    )

    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        # Rebuilding protocol_nodes would temporarily drop a table referenced by
        # many later tables. SQLite rejects that operation while FK checks are
        # enabled, so local/test databases use its native ADD/DROP COLUMN support.
        # The application still supplies a non-null value; PostgreSQL receives the
        # full FK and NOT NULL constraints below.
        op.add_column(
            "protocol_nodes",
            sa.Column("protocol_definition_id", sa.BigInteger()),
        )
        op.create_index(
            "ix_protocol_nodes_protocol_definition_id",
            "protocol_nodes",
            ["protocol_definition_id"],
        )
    else:
        with op.batch_alter_table("protocol_nodes") as batch:
            batch.drop_constraint("ck_protocol_nodes_type", type_="check")
            batch.add_column(sa.Column("protocol_definition_id", sa.BigInteger()))
            batch.create_foreign_key(
                "fk_protocol_nodes_definition_id_protocol_definitions",
                "protocol_definitions",
                ["protocol_definition_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index(
                "ix_protocol_nodes_protocol_definition_id",
                ["protocol_definition_id"],
                unique=False,
            )
    connection.execute(
        sa.text(
            "UPDATE protocol_nodes "
            "SET protocol_definition_id = :definition_id "
            "WHERE protocol_definition_id IS NULL"
        ),
        {"definition_id": definition_id},
    )
    connection.execute(
        sa.text(
            "UPDATE protocol_nodes SET name = '默认节点' "
            "WHERE name = 'Baileys Web协议' "
            "AND remark = '系统默认 Baileys 协议节点'"
        )
    )
    if not is_sqlite:
        with op.batch_alter_table("protocol_nodes") as batch:
            batch.alter_column(
                "protocol_definition_id",
                existing_type=sa.BigInteger(),
                nullable=False,
            )

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
    nodes_menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol"
        )
    ).scalar_one()

    for public_id, temporary_order in (
        ("menu_resources_protocol", 1322),
        ("menu_resources_protocol_routing", 1323),
        ("menu_resources_ip_management", 1324),
    ):
        connection.execute(
            menus.update()
            .where(menus.c.public_id == public_id)
            .values(sort_order=temporary_order)
        )

    definition_menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol_definitions"
        )
    ).scalar_one_or_none()
    if definition_menu_id is None:
        definition_menu_id = _next_snowflake_id(connection, id_tables, offset=1)
        connection.execute(
            menus.insert().values(
                id=definition_menu_id,
                public_id="menu_resources_protocol_definitions",
                parent_id=operations_id,
                name="协议管理",
                menu_type="page",
                route_path="/resources/operations/protocols",
                icon=None,
                permission_key="resources.protocol_definitions.read",
                sort_order=321,
                enabled=True,
                visible=True,
                is_builtin=True,
            )
        )

    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol")
        .values(
            name="节点管理",
            route_path="/resources/operations/nodes",
            sort_order=322,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol_routing")
        .values(sort_order=323)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(sort_order=324)
    )

    role_ids = connection.execute(
        sa.select(role_menus.c.role_id).where(
            role_menus.c.menu_id == nodes_menu_id
        )
    ).scalars()
    offset = 2
    for role_id in role_ids:
        exists = connection.execute(
            sa.select(role_menus.c.id).where(
                role_menus.c.role_id == role_id,
                role_menus.c.menu_id == definition_menu_id,
            )
        ).first()
        if exists:
            continue
        connection.execute(
            role_menus.insert().values(
                id=_next_snowflake_id(connection, id_tables, offset=offset),
                role_id=role_id,
                menu_id=definition_menu_id,
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
    definition_menu_id = connection.execute(
        sa.select(menus.c.id).where(
            menus.c.public_id == "menu_resources_protocol_definitions"
        )
    ).scalar_one_or_none()
    if definition_menu_id is not None:
        connection.execute(
            role_menus.delete().where(role_menus.c.menu_id == definition_menu_id)
        )
        connection.execute(menus.delete().where(menus.c.id == definition_menu_id))
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol")
        .values(
            name="协议管理",
            route_path="/resources/operations/protocol",
            sort_order=321,
        )
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_protocol_routing")
        .values(sort_order=322)
    )
    connection.execute(
        menus.update()
        .where(menus.c.public_id == "menu_resources_ip_management")
        .values(sort_order=323)
    )

    connection.execute(
        sa.text(
            "UPDATE protocol_nodes SET name = 'Baileys Web协议' "
            "WHERE name = '默认节点' "
            "AND remark = '系统默认 Baileys 协议节点'"
        )
    )

    if connection.dialect.name == "sqlite":
        op.drop_index(
            "ix_protocol_nodes_protocol_definition_id",
            table_name="protocol_nodes",
        )
        op.drop_column("protocol_nodes", "protocol_definition_id")
    else:
        with op.batch_alter_table("protocol_nodes") as batch:
            batch.drop_index("ix_protocol_nodes_protocol_definition_id")
            batch.drop_constraint(
                "fk_protocol_nodes_definition_id_protocol_definitions",
                type_="foreignkey",
            )
            batch.drop_column("protocol_definition_id")
            batch.create_check_constraint(
                "ck_protocol_nodes_type", "protocol_type IN ('baileys')"
            )
    op.drop_table("protocol_definitions")
