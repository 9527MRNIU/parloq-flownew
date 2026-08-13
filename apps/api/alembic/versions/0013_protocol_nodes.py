"""Add tenant-scoped Baileys protocol nodes and assign account ownership."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_protocol_nodes"
down_revision: str | None = "0012_unified_navigation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "protocol_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "protocol_type",
            sa.String(24),
            nullable=False,
            server_default="baileys",
        ),
        sa.Column("remark", sa.String(512)),
        sa.Column(
            "ingress_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "marketing_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "online_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
            "protocol_type IN ('baileys')", name="ck_protocol_nodes_type"
        ),
        sa.UniqueConstraint(
            "created_by", "name", name="uq_protocol_nodes_owner_name"
        ),
    )
    for column in (
        "public_id",
        "name",
        "protocol_type",
        "ingress_enabled",
        "marketing_enabled",
        "online_enabled",
        "archived_at",
        "created_by",
    ):
        op.create_index(f"ix_protocol_nodes_{column}", "protocol_nodes", [column])

    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(sa.Column("protocol_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_personal_accounts_protocol_id_protocol_nodes",
            "protocol_nodes",
            ["protocol_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_personal_accounts_protocol_id", ["protocol_id"], unique=False
        )

    bind = op.get_bind()
    users = sa.table("user_accounts", sa.column("id", sa.Integer()))
    nodes = sa.table(
        "protocol_nodes",
        sa.column("id", sa.Integer()),
        sa.column("public_id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("protocol_type", sa.String()),
        sa.column("remark", sa.String()),
        sa.column("ingress_enabled", sa.Boolean()),
        sa.column("marketing_enabled", sa.Boolean()),
        sa.column("online_enabled", sa.Boolean()),
        sa.column("created_by", sa.Integer()),
    )
    accounts = sa.table(
        "personal_accounts",
        sa.column("created_by", sa.Integer()),
        sa.column("protocol_id", sa.Integer()),
    )
    for owner_id in bind.execute(sa.select(users.c.id)).scalars():
        bind.execute(
            nodes.insert().values(
                public_id=f"proto_baileys_{owner_id}",
                name="Baileys 默认协议",
                protocol_type="baileys",
                remark="系统默认 Baileys 协议节点",
                ingress_enabled=True,
                marketing_enabled=True,
                online_enabled=True,
                created_by=owner_id,
            )
        )
        node_id = bind.execute(
            sa.select(nodes.c.id).where(nodes.c.public_id == f"proto_baileys_{owner_id}")
        ).scalar_one()
        bind.execute(
            accounts.update()
            .where(accounts.c.created_by == owner_id)
            .values(protocol_id=node_id)
        )

    with op.batch_alter_table("personal_accounts") as batch:
        batch.alter_column(
            "protocol_id", existing_type=sa.Integer(), nullable=False
        )

    role_actions = sa.Table(
        "role_action_permissions", sa.MetaData(), autoload_with=bind
    )
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    protocol_menu_id = bind.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_resources_protocol")
    ).scalar_one()
    builtin_role_ids = list(
        bind.execute(
            sa.select(roles.c.id).where(
                roles.c.system_key.in_(("admin", "operator"))
            )
        ).scalars()
    )
    for role_id in builtin_role_ids:
        if not bind.execute(
            sa.select(role_actions.c.id).where(
                role_actions.c.role_id == role_id,
                role_actions.c.permission_key == "resources.protocol.manage",
            )
        ).first():
            bind.execute(
                role_actions.insert().values(
                    role_id=role_id,
                    permission_key="resources.protocol.manage",
                )
            )
        if not bind.execute(
            sa.select(role_menus.c.id).where(
                role_menus.c.role_id == role_id,
                role_menus.c.menu_id == protocol_menu_id,
            )
        ).first():
            bind.execute(
                role_menus.insert().values(role_id=role_id, menu_id=protocol_menu_id)
            )


def downgrade() -> None:
    bind = op.get_bind()
    role_actions = sa.Table(
        "role_action_permissions", sa.MetaData(), autoload_with=bind
    )
    bind.execute(
        role_actions.delete().where(
            role_actions.c.permission_key == "resources.protocol.manage"
        )
    )
    menus = sa.Table("system_menus", sa.MetaData(), autoload_with=bind)
    role_menus = sa.Table("role_menu_permissions", sa.MetaData(), autoload_with=bind)
    roles = sa.Table("user_groups", sa.MetaData(), autoload_with=bind)
    protocol_menu_id = bind.execute(
        sa.select(menus.c.id).where(menus.c.public_id == "menu_resources_protocol")
    ).scalar_one()
    builtin_role_ids = sa.select(roles.c.id).where(
        roles.c.system_key == "operator"
    )
    bind.execute(
        role_menus.delete().where(
            role_menus.c.menu_id == protocol_menu_id,
            role_menus.c.role_id.in_(builtin_role_ids),
        )
    )
    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_constraint(
            "fk_personal_accounts_protocol_id_protocol_nodes", type_="foreignkey"
        )
        batch.drop_index("ix_personal_accounts_protocol_id")
        batch.drop_column("protocol_id")
    op.drop_table("protocol_nodes")
