"""add Meta domain monitoring state to promotion channels

Revision ID: 0043_meta_domain_monitoring
Revises: 0042_device_fingerprints
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0043_meta_domain_monitoring"
down_revision = "0042_device_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("promotion_channels") as batch:
        batch.add_column(
            sa.Column(
                "meta_domain_blocked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("meta_domain_blocked_at", sa.DateTime(timezone=True))
        )


def downgrade() -> None:
    with op.batch_alter_table("promotion_channels") as batch:
        batch.drop_column("meta_domain_blocked_at")
        batch.drop_column("meta_domain_blocked")
