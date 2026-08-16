"""add protocol routing, pools, capacity, and sync policy snapshots

Revision ID: 0031_protocol_routing
Revises: 0030_sticky_task_delivery
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0031_protocol_routing"
down_revision = "0030_sticky_task_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        batch.add_column(sa.Column("max_account_count", sa.Integer()))
        batch.add_column(
            sa.Column(
                "max_online_accounts",
                sa.Integer(),
                nullable=True,
                server_default="1000",
            )
        )
        batch.add_column(sa.Column("max_concurrent_pairings", sa.Integer()))
        batch.add_column(
            sa.Column(
                "connection_policy",
                sa.String(24),
                nullable=False,
                server_default="on_demand",
            )
        )
        batch.add_column(
            sa.Column(
                "idle_disconnect_seconds",
                sa.Integer(),
                nullable=False,
                server_default="600",
            )
        )
        batch.add_column(
            sa.Column(
                "post_verify_grace_seconds",
                sa.Integer(),
                nullable=False,
                server_default="120",
            )
        )
        batch.add_column(
            sa.Column(
                "sync_policy_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(
            sa.Column(
                "sync_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        if not sqlite:
            batch.create_check_constraint(
                "ck_protocol_nodes_connection_policy",
                "connection_policy IN ('on_demand', 'always_on')",
            )
            batch.create_check_constraint(
                "ck_protocol_nodes_capacity_nonnegative",
                "(max_account_count IS NULL OR max_account_count >= 0) AND "
                "(max_online_accounts IS NULL OR max_online_accounts >= 0) AND "
                "(max_concurrent_pairings IS NULL OR max_concurrent_pairings >= 0)",
            )
            batch.create_check_constraint(
                "ck_protocol_nodes_connection_windows",
                "idle_disconnect_seconds >= 60 AND "
                "post_verify_grace_seconds >= 0",
            )

    op.create_table(
        "protocol_pools",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("remark", sa.String(512)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "created_by", "name", name="uq_protocol_pools_owner_name"
        ),
    )
    op.create_index("ix_protocol_pools_public_id", "protocol_pools", ["public_id"])
    op.create_index("ix_protocol_pools_name", "protocol_pools", ["name"])
    op.create_index(
        "ix_protocol_pools_archived_at", "protocol_pools", ["archived_at"]
    )
    op.create_index(
        "ix_protocol_pools_created_by", "protocol_pools", ["created_by"]
    )

    op.create_table(
        "protocol_pool_members",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("pool_id", sa.BigInteger(), nullable=False),
        sa.Column("protocol_node_id", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            "priority >= 0", name="ck_protocol_pool_member_priority"
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["protocol_pools.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["protocol_node_id"], ["protocol_nodes.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pool_id", "protocol_node_id", name="uq_protocol_pool_member"
        ),
    )
    op.create_index(
        "ix_protocol_pool_members_pool_id", "protocol_pool_members", ["pool_id"]
    )
    op.create_index(
        "ix_protocol_pool_members_protocol_node_id",
        "protocol_pool_members",
        ["protocol_node_id"],
    )

    with op.batch_alter_table("promotion_channels", recreate=recreate_mode) as batch:
        batch.add_column(sa.Column("protocol_node_id", sa.BigInteger()))
        batch.add_column(sa.Column("protocol_pool_id", sa.BigInteger()))
        batch.add_column(
            sa.Column("route_version", sa.Integer(), nullable=False, server_default="1")
        )
        if not sqlite:
            batch.create_foreign_key(
                "fk_promotion_channels_protocol_node_id_protocol_nodes",
                "protocol_nodes",
                ["protocol_node_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_promotion_channels_protocol_pool_id_protocol_pools",
                "protocol_pools",
                ["protocol_pool_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                "ck_promotion_channels_protocol_route",
                "protocol_node_id IS NULL OR protocol_pool_id IS NULL",
            )
        batch.create_index(
            "ix_promotion_channels_protocol_node_id", ["protocol_node_id"]
        )
        batch.create_index(
            "ix_promotion_channels_protocol_pool_id", ["protocol_pool_id"]
        )

    connection.execute(
        sa.text(
            """
            UPDATE promotion_channels
               SET protocol_node_id = (
                   SELECT personal_accounts.protocol_id
                     FROM personal_accounts
                    WHERE personal_accounts.created_by = promotion_channels.created_by
                      AND personal_accounts.source_ref_id = CAST(promotion_channels.id AS VARCHAR)
                      AND personal_accounts.archived_at IS NULL
                    ORDER BY personal_accounts.created_at, personal_accounts.id
                    LIMIT 1
               )
             WHERE protocol_node_id IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE promotion_channels
               SET protocol_node_id = (
                   SELECT protocol_nodes.id
                     FROM protocol_nodes
                    WHERE protocol_nodes.created_by = promotion_channels.created_by
                      AND protocol_nodes.archived_at IS NULL
                    ORDER BY protocol_nodes.created_at, protocol_nodes.id
                    LIMIT 1
               )
             WHERE protocol_node_id IS NULL
            """
        )
    )

    with op.batch_alter_table("account_pairing_attempts", recreate=recreate_mode) as batch:
        batch.add_column(sa.Column("protocol_node_id", sa.BigInteger()))
        batch.add_column(
            sa.Column("route_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "sync_policy_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(
            sa.Column(
                "sync_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        if not sqlite:
            batch.create_foreign_key(
                "fk_account_pairing_attempts_protocol_node_id_protocol_nodes",
                "protocol_nodes",
                ["protocol_node_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        batch.create_index(
            "ix_account_pairing_attempts_protocol_node_id", ["protocol_node_id"]
        )

    connection.execute(
        sa.text(
            """
            UPDATE account_pairing_attempts
               SET protocol_node_id = (
                   SELECT personal_accounts.protocol_id
                     FROM personal_accounts
                    WHERE personal_accounts.id = account_pairing_attempts.account_id
               )
             WHERE protocol_node_id IS NULL
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("account_pairing_attempts", recreate=recreate_mode) as batch:
        batch.drop_index("ix_account_pairing_attempts_protocol_node_id")
        if not sqlite:
            batch.drop_constraint(
                "fk_account_pairing_attempts_protocol_node_id_protocol_nodes",
                type_="foreignkey",
            )
        batch.drop_column("sync_policy_json")
        batch.drop_column("sync_policy_version")
        batch.drop_column("route_version")
        batch.drop_column("protocol_node_id")

    with op.batch_alter_table("promotion_channels", recreate=recreate_mode) as batch:
        batch.drop_index("ix_promotion_channels_protocol_pool_id")
        batch.drop_index("ix_promotion_channels_protocol_node_id")
        if not sqlite:
            batch.drop_constraint("ck_promotion_channels_protocol_route", type_="check")
            batch.drop_constraint(
                "fk_promotion_channels_protocol_pool_id_protocol_pools",
                type_="foreignkey",
            )
            batch.drop_constraint(
                "fk_promotion_channels_protocol_node_id_protocol_nodes",
                type_="foreignkey",
            )
        batch.drop_column("route_version")
        batch.drop_column("protocol_pool_id")
        batch.drop_column("protocol_node_id")

    op.drop_table("protocol_pool_members")
    op.drop_table("protocol_pools")

    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        if not sqlite:
            batch.drop_constraint("ck_protocol_nodes_connection_windows", type_="check")
            batch.drop_constraint("ck_protocol_nodes_capacity_nonnegative", type_="check")
            batch.drop_constraint("ck_protocol_nodes_connection_policy", type_="check")
        batch.drop_column("sync_policy_json")
        batch.drop_column("sync_policy_version")
        batch.drop_column("post_verify_grace_seconds")
        batch.drop_column("idle_disconnect_seconds")
        batch.drop_column("connection_policy")
        batch.drop_column("max_concurrent_pairings")
        batch.drop_column("max_online_accounts")
        batch.drop_column("max_account_count")
