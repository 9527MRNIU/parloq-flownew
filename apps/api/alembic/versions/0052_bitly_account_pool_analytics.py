"""add Bitly account-pool health and click analytics

Revision ID: 0052_bitly_pool_analytics
Revises: 0051_repository_cache
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0052_bitly_pool_analytics"
down_revision = "0051_repository_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bitly_provider_accounts",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "bitly_provider_accounts",
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "bitly_provider_accounts",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_bitly_provider_accounts_cooldown_until",
        "bitly_provider_accounts",
        ["cooldown_until"],
    )
    op.create_index(
        "ix_bitly_provider_accounts_last_used_at",
        "bitly_provider_accounts",
        ["last_used_at"],
    )
    op.add_column(
        "direct_short_links",
        sa.Column(
            "click_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "direct_short_links",
        sa.Column("clicks_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_direct_short_links_clicks_synced_at",
        "direct_short_links",
        ["clicks_synced_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_direct_short_links_clicks_synced_at",
        table_name="direct_short_links",
    )
    op.drop_column("direct_short_links", "clicks_synced_at")
    op.drop_column("direct_short_links", "click_count")
    op.drop_index(
        "ix_bitly_provider_accounts_last_used_at",
        table_name="bitly_provider_accounts",
    )
    op.drop_index(
        "ix_bitly_provider_accounts_cooldown_until",
        table_name="bitly_provider_accounts",
    )
    op.drop_column("bitly_provider_accounts", "last_used_at")
    op.drop_column("bitly_provider_accounts", "cooldown_until")
    op.drop_column("bitly_provider_accounts", "last_error")
