"""create default account groups for legacy promotion channels

Revision ID: 0029_channel_default_groups
Revises: 0028_channel_account_groups
Create Date: 2026-08-16
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision = "0029_channel_default_groups"
down_revision = "0028_channel_account_groups"
branch_labels = None
depends_on = None


EPOCH_MS = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
MIGRATION_NODE_ID = 1023
DEFAULT_GROUP_NAME = "落地页账号"
DEFAULT_GROUP_DESCRIPTION = "推广渠道自动接入的账号分组"


def _id_tables(connection: sa.Connection) -> tuple[str, ...]:
    inspector = sa.inspect(connection)
    return tuple(
        table
        for table in inspector.get_table_names()
        if any(column["name"] == "id" for column in inspector.get_columns(table))
    )


def _next_snowflake_id(
    connection: sa.Connection,
    id_tables: tuple[str, ...],
    *,
    offset: int,
) -> int:
    timestamp_ms = max(int(datetime.now(UTC).timestamp() * 1000), EPOCH_MS)
    while True:
        candidate_timestamp = timestamp_ms + (offset // 4096)
        sequence = offset % 4096
        candidate = (
            ((candidate_timestamp - EPOCH_MS) << 22)
            | (MIGRATION_NODE_ID << 12)
            | sequence
        )
        if not any(
            connection.execute(
                sa.text(f'SELECT 1 FROM "{table}" WHERE id = :id LIMIT 1'),
                {"id": candidate},
            ).first()
            for table in id_tables
        ):
            return candidate
        offset += 1


def _available_group_name(connection: sa.Connection, owner_id: int) -> str:
    names = {
        str(value)
        for value in connection.execute(
            sa.text("SELECT name FROM account_groups WHERE created_by = :owner_id"),
            {"owner_id": owner_id},
        ).scalars()
    }
    if DEFAULT_GROUP_NAME not in names:
        return DEFAULT_GROUP_NAME
    suffix = 2
    while f"{DEFAULT_GROUP_NAME} {suffix}" in names:
        suffix += 1
    return f"{DEFAULT_GROUP_NAME} {suffix}"


def upgrade() -> None:
    connection = op.get_bind()
    id_tables = _id_tables(connection)
    owner_ids = list(
        connection.execute(
            sa.text(
                """
                SELECT DISTINCT created_by
                  FROM promotion_channels
                 WHERE account_group_id IS NULL
                 ORDER BY created_by
                """
            )
        ).scalars()
    )

    for offset, raw_owner_id in enumerate(owner_ids):
        owner_id = int(raw_owner_id)
        group_id = connection.execute(
            sa.text(
                """
                SELECT id
                  FROM account_groups
                 WHERE created_by = :owner_id
                   AND archived_at IS NULL
                 ORDER BY created_at, id
                 LIMIT 1
                """
            ),
            {"owner_id": owner_id},
        ).scalar_one_or_none()
        if group_id is None:
            group_id = _next_snowflake_id(
                connection,
                id_tables,
                offset=offset,
            )
            now = datetime.now(UTC)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO account_groups (
                        id, public_id, name, description, archived_at,
                        created_by, created_at, updated_at
                    ) VALUES (
                        :id, :public_id, :name, :description, NULL,
                        :owner_id, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": group_id,
                    "public_id": f"ag_{group_id}",
                    "name": _available_group_name(connection, owner_id),
                    "description": DEFAULT_GROUP_DESCRIPTION,
                    "owner_id": owner_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        connection.execute(
            sa.text(
                """
                UPDATE promotion_channels
                   SET account_group_id = :group_id
                 WHERE created_by = :owner_id
                   AND account_group_id IS NULL
                """
            ),
            {"group_id": int(group_id), "owner_id": owner_id},
        )

    connection.execute(
        sa.text(
            """
            UPDATE account_pairing_attempts
               SET account_group_id = (
                   SELECT promotion_channels.account_group_id
                     FROM promotion_channels
                    WHERE promotion_channels.id = account_pairing_attempts.channel_id
               )
             WHERE account_group_id IS NULL
            """
        )
    )


def downgrade() -> None:
    # This migration only repairs ownership data. Once a channel or account has
    # started using the generated group, removing it would destroy user data.
    # Keep the group and assignments when stepping back to the schema-equivalent
    # 0028 revision.
    pass
