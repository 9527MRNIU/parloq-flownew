"""derive number countries from stored E.164 phone numbers

Revision ID: 0062_phone_country_backfill
Revises: 0061_server_promotion_visitors
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.validation import phone_country_code


revision = "0062_phone_country_backfill"
down_revision = "0061_server_promotion_visitors"
branch_labels = None
depends_on = None


PHONE_COUNTRY_TABLES = (
    "personal_accounts",
    "promotion_leads",
    "data_package_recipients",
)


def _backfill_table(table_name: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT id, phone_e164 FROM {table_name}")
    ).mappings()
    statement = sa.text(
        f"UPDATE {table_name} "
        "SET country_code = :country_code WHERE id = :row_id"
    )
    updates: list[dict[str, object]] = []
    for row in rows:
        updates.append(
            {
                "row_id": row["id"],
                "country_code": phone_country_code(row["phone_e164"]),
            }
        )
        if len(updates) >= 1000:
            connection.execute(statement, updates)
            updates.clear()
    if updates:
        connection.execute(
            statement,
            updates,
        )


def upgrade() -> None:
    for table_name in PHONE_COUNTRY_TABLES:
        _backfill_table(table_name)


def downgrade() -> None:
    # Previous values mixed channel, visitor and manually supplied countries,
    # so a downgrade cannot reconstruct them reliably.
    pass
