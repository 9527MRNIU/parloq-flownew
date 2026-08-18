"""store promotion template quality reports

Revision ID: 0047_template_quality
Revises: 0046_integration_packages
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0047_template_quality"
down_revision = "0046_integration_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "promotion_templates",
        sa.Column(
            "quality_report_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        )
    )


def downgrade() -> None:
    op.drop_column("promotion_templates", "quality_report_json")
