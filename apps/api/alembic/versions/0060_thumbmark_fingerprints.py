"""replace configurable device signals with always-on ThumbmarkJS

Revision ID: 0060_thumbmark_fingerprints
Revises: 0059_promotion_request_context
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0060_thumbmark_fingerprints"
down_revision = "0059_promotion_request_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("promotion_template_policies") as batch:
        batch.drop_constraint(
            "ck_promotion_template_policy_device_signals",
            type_="check",
        )
        batch.drop_column("device_signals")


def downgrade() -> None:
    with op.batch_alter_table("promotion_template_policies") as batch:
        batch.add_column(
            sa.Column(
                "device_signals",
                sa.String(16),
                nullable=False,
                server_default="fingerprint",
            )
        )
        batch.create_check_constraint(
            "ck_promotion_template_policy_device_signals",
            "device_signals IN ('off', 'standard', 'enhanced', 'fingerprint')",
        )
