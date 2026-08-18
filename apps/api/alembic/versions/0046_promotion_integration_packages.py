"""store managed promotion integration packages

Revision ID: 0046_integration_packages
Revises: 0045_promotion_integrations
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0046_integration_packages"
down_revision = "0045_promotion_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("promotion_integrations") as batch:
        batch.drop_column("source_path")
        batch.drop_column("integrity")
        batch.add_column(
            sa.Column(
                "entrypoints_json",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "manifest_json",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("asset_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("total_size", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "package_sha256",
                sa.String(length=64),
                server_default="",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "integrities_json",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )

    op.create_table(
        "promotion_integration_assets",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("integration_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
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
            ["integration_id"],
            ["promotion_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "path",
            name="uq_promotion_integration_asset_path",
        ),
    )
    op.create_index(
        "ix_promotion_integration_assets_integration_id",
        "promotion_integration_assets",
        ["integration_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promotion_integration_assets_integration_id",
        table_name="promotion_integration_assets",
    )
    op.drop_table("promotion_integration_assets")
    with op.batch_alter_table("promotion_integrations") as batch:
        batch.drop_column("integrities_json")
        batch.drop_column("package_sha256")
        batch.drop_column("total_size")
        batch.drop_column("asset_count")
        batch.drop_column("manifest_json")
        batch.drop_column("entrypoints_json")
        batch.add_column(
            sa.Column(
                "source_path",
                sa.String(length=1024),
                server_default="",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("integrity", sa.String(length=255)))
