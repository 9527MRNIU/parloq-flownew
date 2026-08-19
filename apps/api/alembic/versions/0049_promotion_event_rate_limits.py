"""add tenant promotion event rate-limit policy

Revision ID: 0049_event_rate_limits
Revises: 0048_integration_feedback
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0049_event_rate_limits"
down_revision = "0048_integration_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table(
        "promotion_template_policies", recreate=recreate_mode
    ) as batch:
        batch.add_column(
            sa.Column(
                "event_rate_limit_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table(
        "promotion_template_policies", recreate=recreate_mode
    ) as batch:
        batch.drop_column("event_rate_limit_policy_json")
