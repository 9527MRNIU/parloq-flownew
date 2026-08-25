"""add non-destructive account retirement metadata

Revision ID: 0073_account_retirement
Revises: 0072_menu_label_updates
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0073_account_retirement"
down_revision = "0072_menu_label_updates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.add_column(sa.Column("deleted_phone_e164", sa.String(length=20)))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("deleted_by", sa.BigInteger()))
        batch.create_foreign_key(
            "fk_personal_accounts_deleted_by_user_accounts",
            "user_accounts",
            ["deleted_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_personal_accounts_deleted_phone_e164",
            ["deleted_phone_e164"],
        )
        batch.create_index("ix_personal_accounts_deleted_at", ["deleted_at"])
        batch.create_index("ix_personal_accounts_deleted_by", ["deleted_by"])


def downgrade() -> None:
    with op.batch_alter_table("personal_accounts") as batch:
        batch.drop_index("ix_personal_accounts_deleted_by")
        batch.drop_index("ix_personal_accounts_deleted_at")
        batch.drop_index("ix_personal_accounts_deleted_phone_e164")
        batch.drop_constraint(
            "fk_personal_accounts_deleted_by_user_accounts",
            type_="foreignkey",
        )
        batch.drop_column("deleted_by")
        batch.drop_column("deleted_at")
        batch.drop_column("deleted_phone_e164")
