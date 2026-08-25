"""allow WhatsApp JIDs as message delivery targets

Revision ID: 0076_message_delivery_targets
Revises: 0075_account_resource_sync
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0076_message_delivery_targets"
down_revision = "0075_account_resource_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message_deliveries") as batch:
        batch.alter_column(
            "recipient_e164",
            existing_type=sa.String(length=20),
            type_=sa.String(length=191),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("message_deliveries") as batch:
        batch.alter_column(
            "recipient_e164",
            existing_type=sa.String(length=191),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
