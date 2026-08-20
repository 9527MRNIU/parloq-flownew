"""persist remote repository snapshots

Revision ID: 0051_repository_cache
Revises: 0050_hard_delete_resources
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0051_repository_cache"
down_revision = "0050_hard_delete_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_repository_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("repository_ref", sa.String(length=255), nullable=False),
        sa.Column("catalog_path", sa.String(length=512), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
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
        sa.UniqueConstraint("platform_key"),
    )
    op.create_index(
        "ix_system_repository_snapshots_platform_key",
        "system_repository_snapshots",
        ["platform_key"],
        unique=True,
    )
    op.create_index(
        "ix_system_repository_snapshots_refreshed_at",
        "system_repository_snapshots",
        ["refreshed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_system_repository_snapshots_refreshed_at",
        table_name="system_repository_snapshots",
    )
    op.drop_index(
        "ix_system_repository_snapshots_platform_key",
        table_name="system_repository_snapshots",
    )
    op.drop_table("system_repository_snapshots")
