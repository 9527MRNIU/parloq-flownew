"""add platform settings and connection test state

Revision ID: 0039_platform_configuration
Revises: 0038_system_configuration
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0039_platform_configuration"
down_revision = "0038_system_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_platform_configurations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("settings_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "last_test_status",
            sa.String(length=24),
            server_default="untested",
            nullable=False,
        ),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
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
            ["updated_by"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_key"),
    )
    op.create_index(
        "ix_system_platform_configurations_platform_key",
        "system_platform_configurations",
        ["platform_key"],
        unique=True,
    )
    op.create_index(
        "ix_system_platform_configurations_enabled",
        "system_platform_configurations",
        ["enabled"],
    )
    op.create_index(
        "ix_system_platform_configurations_last_test_status",
        "system_platform_configurations",
        ["last_test_status"],
    )
    op.create_index(
        "ix_system_platform_configurations_updated_by",
        "system_platform_configurations",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_system_platform_configurations_updated_by",
        table_name="system_platform_configurations",
    )
    op.drop_index(
        "ix_system_platform_configurations_last_test_status",
        table_name="system_platform_configurations",
    )
    op.drop_index(
        "ix_system_platform_configurations_enabled",
        table_name="system_platform_configurations",
    )
    op.drop_index(
        "ix_system_platform_configurations_platform_key",
        table_name="system_platform_configurations",
    )
    op.drop_table("system_platform_configurations")
