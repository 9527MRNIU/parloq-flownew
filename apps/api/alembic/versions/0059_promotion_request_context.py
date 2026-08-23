"""store server-owned promotion request context

Revision ID: 0059_promotion_request_context
Revises: 0058_promotion_network_context
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0059_promotion_request_context"
down_revision = "0058_promotion_network_context"
branch_labels = None
depends_on = None


TABLES = (
    "promotion_events",
    "promotion_integration_events",
    "account_pairing_attempts",
)


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "request_context_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )


def downgrade() -> None:
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("request_context_json")
