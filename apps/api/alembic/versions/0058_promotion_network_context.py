"""add promotion request network context

Revision ID: 0058_promotion_network_context
Revises: 0057_visit_monitoring
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0058_promotion_network_context"
down_revision = "0057_visit_monitoring"
branch_labels = None
depends_on = None


TABLES = (
    "promotion_events",
    "promotion_integration_events",
    "account_pairing_attempts",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("source_ip", sa.String(length=45)))
        op.add_column(
            table,
            sa.Column("visitor_country_code", sa.String(length=2)),
        )
        op.add_column(table, sa.Column("network_source", sa.String(length=16)))
        op.create_index(f"ix_{table}_source_ip", table, ["source_ip"])
        op.create_index(
            f"ix_{table}_visitor_country_code",
            table,
            ["visitor_country_code"],
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_visitor_country_code", table_name=table)
        op.drop_index(f"ix_{table}_source_ip", table_name=table)
        op.drop_column(table, "network_source")
        op.drop_column(table, "visitor_country_code")
        op.drop_column(table, "source_ip")
