"""store independent iframe integration feedback

Revision ID: 0048_integration_feedback
Revises: 0047_template_quality
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0048_integration_feedback"
down_revision = "0047_template_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotion_integration_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("integration_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("integration_version", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("visitor_id", sa.String(length=80), nullable=True),
        sa.Column("visitor_fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("fingerprint_version", sa.String(length=40), nullable=True),
        sa.Column("fingerprint_quality", sa.String(length=16), nullable=True),
        sa.Column(
            "traffic_source",
            sa.String(length=16),
            server_default="direct",
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["integration_id"], ["promotion_integrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["promotion_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["promotion_templates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "integration_id",
            "channel_id",
            "idempotency_key",
            name="uq_promotion_integration_event_idem",
        ),
    )
    for column in (
        "public_id",
        "integration_id",
        "channel_id",
        "template_id",
        "event_type",
        "visitor_id",
        "visitor_fingerprint_hash",
        "occurred_at",
        "country_code",
    ):
        op.create_index(
            f"ix_promotion_integration_events_{column}",
            "promotion_integration_events",
            [column],
        )
    op.create_index(
        "ix_promotion_integration_events_integration_occurred",
        "promotion_integration_events",
        ["integration_id", "occurred_at"],
    )
    op.create_index(
        "ix_promotion_integration_events_channel_occurred",
        "promotion_integration_events",
        ["channel_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("promotion_integration_events")
