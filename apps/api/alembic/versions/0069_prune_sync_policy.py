"""remove unused metadata sync policy fields

Revision ID: 0069_prune_sync_policy
Revises: 0068_proxy_health_cooldown
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0069_prune_sync_policy"
down_revision = "0068_proxy_health_cooldown"
branch_labels = None
depends_on = None


SYNC_POLICY_TABLES = (
    "protocol_nodes",
    "account_pairing_attempts",
    "account_metadata_sync_jobs",
)
REMOVED_KEYS = (
    "profileStatus",
    "profile_status",
    "businessProfile",
    "business_profile",
    "privacySettings",
    "privacy_settings",
    "blocklist",
)
RESTORED_DEFAULTS = {
    "profileStatus": True,
    "businessProfile": True,
    "privacySettings": False,
    "blocklist": False,
}


def _rewrite_policies(transform) -> None:
    connection = op.get_bind()
    for table_name in SYNC_POLICY_TABLES:
        table = sa.table(
            table_name,
            sa.column("id", sa.BigInteger()),
            sa.column("sync_policy_json", sa.JSON()),
        )
        rows = connection.execute(
            sa.select(table.c.id, table.c.sync_policy_json)
        ).mappings()
        for row in rows:
            value = row["sync_policy_json"]
            if not isinstance(value, dict):
                continue
            updated = transform(dict(value))
            if updated != value:
                connection.execute(
                    table.update()
                    .where(table.c.id == row["id"])
                    .values(sync_policy_json=updated)
                )


def upgrade() -> None:
    def remove_unused_fields(value: dict) -> dict:
        for key in REMOVED_KEYS:
            value.pop(key, None)
        return value

    _rewrite_policies(remove_unused_fields)


def downgrade() -> None:
    def restore_defaults(value: dict) -> dict:
        for key, default in RESTORED_DEFAULTS.items():
            value.setdefault(key, default)
        return value

    _rewrite_policies(restore_defaults)
