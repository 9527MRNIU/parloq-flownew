"""defer metadata sync until the post-verify stability window ends

Revision ID: 0080_metadata_sync_window
Revises: 0079_protocol_pairing_codes
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0080_metadata_sync_window"
down_revision = "0079_protocol_pairing_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_metadata_sync_jobs") as batch:
        batch.drop_index("ix_account_metadata_sync_jobs_pending")
        batch.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch.create_index(
            "ix_account_metadata_sync_jobs_pending",
            ["status", "available_at", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("account_metadata_sync_jobs") as batch:
        batch.drop_index("ix_account_metadata_sync_jobs_pending")
        batch.drop_column("available_at")
        batch.create_index(
            "ix_account_metadata_sync_jobs_pending",
            ["status", "created_at"],
        )
