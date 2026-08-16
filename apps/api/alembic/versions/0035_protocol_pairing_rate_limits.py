"""add protocol-owned public pairing rate-limit policy

Revision ID: 0035_protocol_rate_limits
Revises: 0034_account_admission_sync
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_protocol_rate_limits"
down_revision = "0034_account_admission_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        batch.add_column(
            sa.Column(
                "rate_limit_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        batch.drop_column("rate_limit_policy_json")
