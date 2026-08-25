"""add group last interaction time

Revision ID: 0077_group_last_interaction
Revises: 0076_message_delivery_targets
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0077_group_last_interaction"
down_revision = "0076_message_delivery_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_whatsapp_groups") as batch:
        batch.add_column(sa.Column("last_interaction_at", sa.DateTime(timezone=True)))
        batch.create_index(
            "ix_account_whatsapp_groups_last_interaction_at",
            ["last_interaction_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("account_whatsapp_groups") as batch:
        batch.drop_index("ix_account_whatsapp_groups_last_interaction_at")
        batch.drop_column("last_interaction_at")
