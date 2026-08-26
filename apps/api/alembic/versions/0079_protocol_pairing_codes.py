"""add protocol node pairing code modes

Revision ID: 0079_protocol_pairing_codes
Revises: 0078_provider_domain_cache
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0079_protocol_pairing_codes"
down_revision = "0078_provider_domain_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        batch.add_column(sa.Column("pairing_code_mode", sa.String(length=24)))
        batch.add_column(sa.Column("fixed_pairing_code", sa.String(length=8)))
        if not sqlite:
            batch.create_check_constraint(
                "ck_protocol_nodes_pairing_code_mode",
                "pairing_code_mode IS NULL OR pairing_code_mode IN "
                "('fixed', 'random_numeric', 'random_alphanumeric')",
            )
            batch.create_check_constraint(
                "ck_protocol_nodes_fixed_pairing_code_length",
                "fixed_pairing_code IS NULL OR length(fixed_pairing_code) = 8",
            )


def downgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    recreate_mode = "never" if sqlite else "auto"
    with op.batch_alter_table("protocol_nodes", recreate=recreate_mode) as batch:
        if not sqlite:
            batch.drop_constraint(
                "ck_protocol_nodes_fixed_pairing_code_length", type_="check"
            )
            batch.drop_constraint(
                "ck_protocol_nodes_pairing_code_mode", type_="check"
            )
        batch.drop_column("fixed_pairing_code")
        batch.drop_column("pairing_code_mode")
