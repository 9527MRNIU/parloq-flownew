"""store pairing failure diagnosis

Revision ID: 0071_pairing_failure_diagnosis
Revises: 0070_account_avatar_cache
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0071_pairing_failure_diagnosis"
down_revision = "0070_account_avatar_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.add_column(
            sa.Column(
                "failure_detail_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.drop_column("failure_detail_json")
