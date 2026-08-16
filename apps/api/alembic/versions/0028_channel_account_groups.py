"""bind promotion channels to account groups and add durable wakeup events

Revision ID: 0028_channel_account_groups
Revises: 0027_dynamic_account_groups
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0028_channel_account_groups"
down_revision = "0027_dynamic_account_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("promotion_channels") as batch:
        batch.add_column(sa.Column("account_group_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_promotion_channels_account_group_id_account_groups",
            "account_groups",
            ["account_group_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_promotion_channels_account_group_id", ["account_group_id"]
        )

    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.add_column(sa.Column("account_group_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_account_pairing_attempts_account_group_id_account_groups",
            "account_groups",
            ["account_group_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_account_pairing_attempts_account_group_id", ["account_group_id"]
        )

    # Preserve the existing development/production channels when the new
    # routing field is introduced. Prefer the group already used by an
    # account that entered through that channel, then fall back to the
    # tenant's oldest active group. The value is only a channel default;
    # individual pairing attempts snapshot it below.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE promotion_channels
               SET account_group_id = (
                   SELECT personal_accounts.group_id
                     FROM personal_accounts
                    WHERE personal_accounts.created_by = promotion_channels.created_by
                      AND personal_accounts.source_ref_id = CAST(promotion_channels.id AS VARCHAR)
                      AND personal_accounts.group_id IS NOT NULL
                      AND personal_accounts.archived_at IS NULL
                    ORDER BY personal_accounts.created_at, personal_accounts.id
                    LIMIT 1
               )
             WHERE account_group_id IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE promotion_channels
               SET account_group_id = (
                   SELECT account_groups.id
                     FROM account_groups
                    WHERE account_groups.created_by = promotion_channels.created_by
                      AND account_groups.archived_at IS NULL
                    ORDER BY account_groups.created_at, account_groups.id
                    LIMIT 1
               )
             WHERE account_group_id IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE account_pairing_attempts
               SET account_group_id = (
                   SELECT promotion_channels.account_group_id
                     FROM promotion_channels
                    WHERE promotion_channels.id = account_pairing_attempts.channel_id
               )
             WHERE account_group_id IS NULL
            """
        )
    )

    op.create_table(
        "account_group_wakeup_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["account_groups.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_group_wakeup_events_account_id",
        "account_group_wakeup_events",
        ["account_id"],
    )
    op.create_index(
        "ix_account_group_wakeup_events_group_id",
        "account_group_wakeup_events",
        ["group_id"],
    )
    op.create_index(
        "ix_account_group_wakeup_events_processed_at",
        "account_group_wakeup_events",
        ["processed_at"],
    )
    op.create_index(
        "ix_account_group_wakeup_events_pending",
        "account_group_wakeup_events",
        ["processed_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_group_wakeup_events_pending",
        table_name="account_group_wakeup_events",
    )
    op.drop_index(
        "ix_account_group_wakeup_events_processed_at",
        table_name="account_group_wakeup_events",
    )
    op.drop_index(
        "ix_account_group_wakeup_events_group_id",
        table_name="account_group_wakeup_events",
    )
    op.drop_index(
        "ix_account_group_wakeup_events_account_id",
        table_name="account_group_wakeup_events",
    )
    op.drop_table("account_group_wakeup_events")

    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.drop_index("ix_account_pairing_attempts_account_group_id")
        batch.drop_constraint(
            "fk_account_pairing_attempts_account_group_id_account_groups",
            type_="foreignkey",
        )
        batch.drop_column("account_group_id")

    with op.batch_alter_table("promotion_channels") as batch:
        batch.drop_index("ix_promotion_channels_account_group_id")
        batch.drop_constraint(
            "fk_promotion_channels_account_group_id_account_groups",
            type_="foreignkey",
        )
        batch.drop_column("account_group_id")
