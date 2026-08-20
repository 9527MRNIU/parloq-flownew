"""replace business-resource archiving with hard deletion

Revision ID: 0050_hard_delete_resources
Revises: 0049_event_rate_limits
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0050_hard_delete_resources"
down_revision = "0049_event_rate_limits"
branch_labels = None
depends_on = None


ARCHIVED_TABLES = (
    "bitly_provider_accounts",
    "direct_short_links",
    "meta_pixels",
    "proxy_endpoints",
    "account_groups",
    "protocol_nodes",
    "protocol_pools",
    "personal_accounts",
    "domains",
    "promotion_templates",
    "promotion_integrations",
    "promotion_channels",
    "materials",
    "hyperlink_templates",
    "hyperlink_strategies",
    "data_packages",
    "hyperlink_tasks",
)


def _drop_archive_columns() -> None:
    connection = op.get_bind()
    for table_name in ARCHIVED_TABLES:
        index_name = f"ix_{table_name}_archived_at"
        existing_indexes = {
            str(index["name"])
            for index in sa.inspect(connection).get_indexes(table_name)
        }
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "archived_at")


def upgrade() -> None:
    # Delete former soft-deleted rows in dependency order. Rows that belonged to
    # a deleted parent are deleted too, matching the new hard-delete semantics.
    op.execute(
        """
        DELETE FROM direct_short_links
        WHERE archived_at IS NOT NULL
           OR provider_account_id IN (
               SELECT id FROM bitly_provider_accounts WHERE archived_at IS NOT NULL
           )
        """
    )
    op.execute(
        """
        DELETE FROM account_proxy_bindings
        WHERE proxy_id IN (
            SELECT id FROM proxy_endpoints WHERE archived_at IS NOT NULL
        )
        """
    )
    op.execute(
        """
        DELETE FROM meta_conversion_deliveries
        WHERE pixel_id IN (
            SELECT id FROM meta_pixels WHERE archived_at IS NOT NULL
        )
        """
    )
    op.execute(
        """
        DELETE FROM message_deliveries
        WHERE account_id IN (
            SELECT id FROM personal_accounts WHERE archived_at IS NOT NULL
        )
        """
    )
    op.execute(
        """
        DELETE FROM account_metadata_sync_jobs
        WHERE account_id IN (
                SELECT id FROM personal_accounts WHERE archived_at IS NOT NULL
              )
           OR protocol_node_id IN (
                SELECT id FROM protocol_nodes WHERE archived_at IS NOT NULL
              )
        """
    )
    op.execute(
        """
        DELETE FROM account_pairing_attempts
        WHERE account_id IN (
                SELECT id FROM personal_accounts WHERE archived_at IS NOT NULL
              )
           OR channel_id IN (
                SELECT id FROM promotion_channels WHERE archived_at IS NOT NULL
              )
           OR account_group_id IN (
                SELECT id FROM account_groups WHERE archived_at IS NOT NULL
              )
           OR protocol_node_id IN (
                SELECT id FROM protocol_nodes WHERE archived_at IS NOT NULL
              )
        """
    )
    op.execute("DELETE FROM hyperlink_tasks WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM promotion_channels WHERE archived_at IS NOT NULL")
    op.execute(
        """
        DELETE FROM promotion_integrations
        WHERE archived_at IS NOT NULL
           OR source_domain_id IN (
               SELECT id FROM domains WHERE archived_at IS NOT NULL
           )
        """
    )
    op.execute("DELETE FROM personal_accounts WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM hyperlink_templates WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM hyperlink_strategies WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM data_packages WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM materials WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM promotion_templates WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM meta_pixels WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM domains WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM protocol_pools WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM protocol_nodes WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM account_groups WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM proxy_endpoints WHERE archived_at IS NOT NULL")
    op.execute("DELETE FROM bitly_provider_accounts WHERE archived_at IS NOT NULL")
    _drop_archive_columns()


def downgrade() -> None:
    for table_name in reversed(ARCHIVED_TABLES):
        op.add_column(
            table_name,
            sa.Column("archived_at", sa.DateTime(timezone=True)),
        )
        op.create_index(
            f"ix_{table_name}_archived_at",
            table_name,
            ["archived_at"],
        )
