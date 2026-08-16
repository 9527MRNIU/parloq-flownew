"""schedule hyperlink tasks from live account-group membership

Revision ID: 0027_dynamic_account_groups
Revises: 0026_task_observability
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0027_dynamic_account_groups"
down_revision = "0026_task_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.add_column(sa.Column("account_group_id", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column(
                "sender_mode",
                sa.String(16),
                nullable=False,
                server_default="legacy_fixed",
            )
        )
        batch.create_foreign_key(
            "fk_hyperlink_tasks_account_group_id_account_groups",
            "account_groups",
            ["account_group_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_hyperlink_tasks_account_group_id", ["account_group_id"]
        )
        batch.create_index("ix_hyperlink_tasks_sender_mode", ["sender_mode"])
        batch.create_check_constraint(
            "ck_hyperlink_tasks_sender_mode",
            "sender_mode IN ('legacy_fixed', 'dynamic_group')",
        )


def downgrade() -> None:
    with op.batch_alter_table("hyperlink_tasks") as batch:
        batch.drop_constraint(
            "ck_hyperlink_tasks_sender_mode", type_="check"
        )
        batch.drop_index("ix_hyperlink_tasks_sender_mode")
        batch.drop_index("ix_hyperlink_tasks_account_group_id")
        batch.drop_constraint(
            "fk_hyperlink_tasks_account_group_id_account_groups",
            type_="foreignkey",
        )
        batch.drop_column("sender_mode")
        batch.drop_column("account_group_id")
