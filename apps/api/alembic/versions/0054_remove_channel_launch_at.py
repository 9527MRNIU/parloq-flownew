"""remove scheduled channel launch

Revision ID: 0054_remove_channel_launch
Revises: 0053_pixel_runtime_config
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0054_remove_channel_launch"
down_revision = "0053_pixel_runtime_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    index_name = "ix_promotion_channels_launch_at"
    indexes = {
        str(index["name"])
        for index in sa.inspect(connection).get_indexes("promotion_channels")
    }
    if index_name in indexes:
        op.drop_index(index_name, table_name="promotion_channels")
    op.drop_column("promotion_channels", "launch_at")


def downgrade() -> None:
    op.add_column(
        "promotion_channels",
        sa.Column("launch_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_promotion_channels_launch_at",
        "promotion_channels",
        ["launch_at"],
    )
