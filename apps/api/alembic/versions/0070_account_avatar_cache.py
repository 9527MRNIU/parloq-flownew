"""cache downloaded account avatars

Revision ID: 0070_account_avatar_cache
Revises: 0069_prune_sync_policy
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0070_account_avatar_cache"
down_revision = "0069_prune_sync_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(sa.Column("avatar_source_url", sa.Text()))
        batch.add_column(sa.Column("avatar_content_type", sa.String(length=64)))
        batch.add_column(sa.Column("avatar_size", sa.Integer()))
        batch.add_column(sa.Column("avatar_sha256", sa.String(length=64)))
        batch.add_column(sa.Column("avatar_content", sa.LargeBinary()))
        batch.add_column(sa.Column("avatar_fetched_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_column("avatar_fetched_at")
        batch.drop_column("avatar_content")
        batch.drop_column("avatar_sha256")
        batch.drop_column("avatar_size")
        batch.drop_column("avatar_content_type")
        batch.drop_column("avatar_source_url")
