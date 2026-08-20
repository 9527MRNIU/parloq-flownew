"""add optional TOTP multi-factor authentication

Revision ID: 0055_optional_totp_mfa
Revises: 0054_remove_channel_launch
Create Date: 2026-08-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0055_optional_totp_mfa"
down_revision = "0054_remove_channel_launch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_mfa_credentials",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("recovery_code_hashes", sa.JSON(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_counter", sa.BigInteger()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_user_mfa_credentials_user_id", "user_mfa_credentials", ["user_id"], unique=True
    )
    op.create_index(
        "ix_user_mfa_credentials_enabled_at", "user_mfa_credentials", ["enabled_at"]
    )

    op.create_table(
        "mfa_login_challenges",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_mfa_login_challenges_token_hash", "mfa_login_challenges", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_mfa_login_challenges_user_id", "mfa_login_challenges", ["user_id"]
    )
    op.create_index(
        "ix_mfa_login_challenges_expires_at", "mfa_login_challenges", ["expires_at"]
    )
    op.create_index(
        "ix_mfa_login_challenges_consumed_at", "mfa_login_challenges", ["consumed_at"]
    )

    op.create_table(
        "mfa_security_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("actor_user_id", sa.BigInteger()),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source_ip_hash", sa.String(length=64)),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mfa_security_events_user_id", "mfa_security_events", ["user_id"])
    op.create_index(
        "ix_mfa_security_events_actor_user_id", "mfa_security_events", ["actor_user_id"]
    )
    op.create_index(
        "ix_mfa_security_events_event_type", "mfa_security_events", ["event_type"]
    )
    op.create_index(
        "ix_mfa_security_events_created_at", "mfa_security_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("mfa_security_events")
    op.drop_table("mfa_login_challenges")
    op.drop_table("user_mfa_credentials")
