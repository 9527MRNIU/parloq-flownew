"""persist provider domain inventories

Revision ID: 0078_provider_domain_cache
Revises: 0077_group_last_interaction
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0078_provider_domain_cache"
down_revision = "0077_group_last_interaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_domain_caches",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("provider_created_at", sa.DateTime(timezone=True)),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "hostname",
            name="uq_provider_domain_cache_provider_hostname",
        ),
    )
    op.create_index(
        "ix_provider_domain_caches_provider_id",
        "provider_domain_caches",
        ["provider", "id"],
    )


def downgrade() -> None:
    op.drop_table("provider_domain_caches")
