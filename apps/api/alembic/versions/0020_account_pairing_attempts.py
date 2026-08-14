"""add durable public account pairing attempts

Revision ID: 0020_account_pairing_attempts
Revises: 0019_snowflake_ids
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_account_pairing_attempts"
down_revision = "0019_snowflake_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_pairing_attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("visitor_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_reason", sa.String(length=64), nullable=True),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
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
            "status IN ('code_issued', 'waiting_phone', 'reconnecting', 'verified', 'expired', 'cancelled', 'failed')",
            name="ck_account_pairing_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["personal_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["promotion_channels.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_account_pairing_attempts_public_id",
        "account_pairing_attempts",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        "ix_account_pairing_attempts_account_id",
        "account_pairing_attempts",
        ["account_id"],
    )
    op.create_index(
        "ix_account_pairing_attempts_channel_id",
        "account_pairing_attempts",
        ["channel_id"],
    )
    op.create_index(
        "ix_account_pairing_attempts_visitor_id",
        "account_pairing_attempts",
        ["visitor_id"],
    )
    op.create_index(
        "ix_account_pairing_attempts_status",
        "account_pairing_attempts",
        ["status"],
    )
    op.create_index(
        "ix_account_pairing_attempts_expires_at",
        "account_pairing_attempts",
        ["expires_at"],
    )
    op.create_index(
        "ix_account_pairing_attempts_account_created",
        "account_pairing_attempts",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_account_pairing_attempts_channel_visitor_created",
        "account_pairing_attempts",
        ["channel_id", "visitor_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_pairing_attempts_channel_visitor_created",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_account_created",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_expires_at",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_status",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_visitor_id",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_channel_id",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_account_id",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_public_id",
        table_name="account_pairing_attempts",
    )
    op.drop_table("account_pairing_attempts")
