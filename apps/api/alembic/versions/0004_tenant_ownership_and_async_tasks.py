"""Add tenant ownership and async hyperlink delivery attempts."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_tenant_ownership_async"
down_revision: str | None = "0003_business_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OWNER_TABLES = (
    "meta_pixels",
    "domains",
    "promotion_templates",
    "promotion_channels",
    "hyperlink_materials",
    "hyperlink_templates",
    "hyperlink_strategies",
    "data_packages",
    "hyperlink_tasks",
)


def upgrade() -> None:
    for table in OWNER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_created_by_user_accounts",
                "user_accounts",
                ["created_by"],
                ["id"],
                ondelete="RESTRICT",
            )
    for table in OWNER_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET created_by = "
                "(SELECT id FROM user_accounts ORDER BY "
                "CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id LIMIT 1) "
                "WHERE created_by IS NULL"
            )
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("created_by", existing_type=sa.Integer(), nullable=False)
            batch.create_index(f"ix_{table}_created_by", ["created_by"])

    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hyperlink_task_deliveries") as batch:
        batch.drop_column("last_error")
        batch.drop_column("attempt_count")
    for table in reversed(OWNER_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_created_by")
            batch.drop_constraint(
                f"fk_{table}_created_by_user_accounts", type_="foreignkey"
            )
            batch.drop_column("created_by")
