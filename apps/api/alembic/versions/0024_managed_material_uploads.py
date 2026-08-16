"""store uploaded material files inside the managed material library

Revision ID: 0024_managed_material_uploads
Revises: 0023_global_material_library
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024_managed_material_uploads"
down_revision = "0023_global_material_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.add_column(sa.Column("file_name", sa.String(180), nullable=True))
        batch.add_column(sa.Column("content_type", sa.String(120), nullable=True))
        batch.add_column(sa.Column("file_size", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("file_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("content", sa.LargeBinary(), nullable=True))
        batch.create_index("ix_materials_file_sha256", ["file_sha256"])


def downgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.drop_index("ix_materials_file_sha256")
        batch.drop_column("content")
        batch.drop_column("file_sha256")
        batch.drop_column("file_size")
        batch.drop_column("content_type")
        batch.drop_column("file_name")
