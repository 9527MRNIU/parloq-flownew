"""Add tenant-owned promotion template policy."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_promotion_template_policy"
down_revision: str | None = "0015_account_analytics_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promotion_template_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protection_mode",
            sa.String(16),
            nullable=False,
            server_default="basic",
        ),
        sa.Column(
            "devtools_action",
            sa.String(16),
            nullable=False,
            server_default="log",
        ),
        sa.Column(
            "lock_viewport_zoom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "device_signals",
            sa.String(16),
            nullable=False,
            server_default="standard",
        ),
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
            "protection_mode IN ('basic', 'enhanced', 'strict')",
            name="ck_promotion_template_policy_protection_mode",
        ),
        sa.CheckConstraint(
            "devtools_action IN ('log', 'block', 'blank')",
            name="ck_promotion_template_policy_devtools_action",
        ),
        sa.CheckConstraint(
            "device_signals IN ('off', 'standard', 'enhanced')",
            name="ck_promotion_template_policy_device_signals",
        ),
        sa.UniqueConstraint(
            "created_by", name="uq_promotion_template_policy_owner"
        ),
    )
    op.create_index(
        "ix_promotion_template_policies_created_by",
        "promotion_template_policies",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("promotion_template_policies")
