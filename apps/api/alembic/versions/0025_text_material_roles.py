"""add indexed usage roles to text materials

Revision ID: 0025_text_material_roles
Revises: 0024_managed_material_uploads
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_text_material_roles"
down_revision = "0024_managed_material_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.add_column(sa.Column("text_role", sa.String(16), nullable=True))
        batch.create_index("ix_materials_text_role", ["text_role"])
    op.execute(
        sa.text(
            "UPDATE materials SET text_role = 'body' "
            "WHERE material_type = 'text' AND text_role IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.drop_index("ix_materials_text_role")
        batch.drop_column("text_role")
