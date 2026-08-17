"""repair sticky-delivery columns missing from already-stamped databases

Revision ID: 0036_sticky_delivery_repair
Revises: 0035_developer_docs
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_sticky_delivery_repair"
down_revision = "0035_developer_docs"
branch_labels = None
depends_on = None


def _column_names(connection: sa.Connection, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(connection).get_columns(table_name)
    }


def _index_names(connection: sa.Connection, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(connection).get_indexes(table_name)
        if index["name"]
    }


def upgrade() -> None:
    """Reconcile databases stamped after an earlier form of revision 0030.

    Some development and early release databases reached later Alembic
    revisions before these sticky-delivery fields were part of 0030.  Since
    Alembic correctly considers 0030 applied, only a new forward migration can
    safely repair those databases.  Fresh databases already have every field,
    so all operations below are intentionally conditional.
    """

    connection = op.get_bind()

    personal_columns = _column_names(connection, "personal_accounts")
    personal_indexes = _index_names(connection, "personal_accounts")
    with op.batch_alter_table("personal_accounts") as batch:
        if "sending_cooldown_until" not in personal_columns:
            batch.add_column(
                sa.Column("sending_cooldown_until", sa.DateTime(timezone=True))
            )
        if "ix_personal_accounts_sending_cooldown_until" not in personal_indexes:
            batch.create_index(
                "ix_personal_accounts_sending_cooldown_until",
                ["sending_cooldown_until"],
            )

    recipient_columns = _column_names(connection, "data_package_recipients")
    recipient_indexes = _index_names(connection, "data_package_recipients")
    with op.batch_alter_table("data_package_recipients") as batch:
        if "package_revision" not in recipient_columns:
            batch.add_column(
                sa.Column(
                    "package_revision",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                )
            )
        if "removed_revision" not in recipient_columns:
            batch.add_column(sa.Column("removed_revision", sa.Integer()))
        if "ix_data_package_recipients_package_revision" not in recipient_indexes:
            batch.create_index(
                "ix_data_package_recipients_package_revision",
                ["package_revision"],
            )
        if "ix_data_package_recipients_removed_revision" not in recipient_indexes:
            batch.create_index(
                "ix_data_package_recipients_removed_revision",
                ["removed_revision"],
            )

    task_columns = _column_names(connection, "hyperlink_tasks")
    if "skipped_count" not in task_columns:
        with op.batch_alter_table("hyperlink_tasks") as batch:
            batch.add_column(
                sa.Column(
                    "skipped_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    # These columns belong to the 0030 schema.  Removing them when stepping
    # back across this repair would recreate the drift this migration fixes.
    pass
