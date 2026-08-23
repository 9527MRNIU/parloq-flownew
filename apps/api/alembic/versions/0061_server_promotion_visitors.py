"""replace browser visitor ids with server-owned promotion visitors

Revision ID: 0061_server_promotion_visitors
Revises: 0060_thumbmark_fingerprints
Create Date: 2026-08-24
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.snowflake import next_snowflake_id


revision = "0061_server_promotion_visitors"
down_revision = "0060_thumbmark_fingerprints"
branch_labels = None
depends_on = None


EVENT_TABLES = (
    "promotion_events",
    "promotion_integration_events",
    "account_pairing_attempts",
)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def _backfill_visitors() -> None:
    connection = op.get_bind()
    discovered: dict[tuple[int, str], dict] = {}
    for table in EVENT_TABLES:
        rows = connection.execute(
            sa.text(
                f"""
                SELECT c.created_by AS tenant_id,
                       e.visitor_fingerprint_hash AS fingerprint_hash,
                       e.fingerprint_version AS fingerprint_version,
                       e.fingerprint_quality AS fingerprint_quality,
                       e.created_at AS seen_at
                FROM {table} e
                JOIN promotion_channels c ON c.id = e.channel_id
                WHERE e.visitor_fingerprint_hash IS NOT NULL
                """
            )
        ).mappings()
        for row in rows:
            key = (int(row["tenant_id"]), str(row["fingerprint_hash"]))
            seen_at = _as_datetime(row["seen_at"])
            current = discovered.get(key)
            if current is None:
                discovered[key] = {
                    "id": next_snowflake_id(),
                    "tenant_id": key[0],
                    "fingerprint_hash": key[1],
                    "fingerprint_version": str(
                        row["fingerprint_version"] or "legacy"
                    ),
                    "fingerprint_quality": str(
                        row["fingerprint_quality"] or "low"
                    ),
                    "first_seen_at": seen_at,
                    "last_seen_at": seen_at,
                    "created_at": seen_at,
                    "updated_at": seen_at,
                }
            else:
                current["first_seen_at"] = min(current["first_seen_at"], seen_at)
                current["last_seen_at"] = max(current["last_seen_at"], seen_at)
                current["updated_at"] = current["last_seen_at"]
    if discovered:
        visitors = sa.table(
            "promotion_visitors",
            sa.column("id", sa.BigInteger()),
            sa.column("tenant_id", sa.BigInteger()),
            sa.column("fingerprint_hash", sa.String(64)),
            sa.column("fingerprint_version", sa.String(40)),
            sa.column("fingerprint_quality", sa.String(16)),
            sa.column("first_seen_at", sa.DateTime(timezone=True)),
            sa.column("last_seen_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(visitors, list(discovered.values()))


def upgrade() -> None:
    op.create_table(
        "promotion_visitors",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint_version", sa.String(40), nullable=False),
        sa.Column("fingerprint_quality", sa.String(16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "fingerprint_hash",
            name="uq_promotion_visitor_tenant_fingerprint",
        ),
    )
    op.create_index(
        "ix_promotion_visitors_tenant_id", "promotion_visitors", ["tenant_id"]
    )
    op.create_index(
        "ix_promotion_visitors_first_seen_at",
        "promotion_visitors",
        ["first_seen_at"],
    )
    op.create_index(
        "ix_promotion_visitors_last_seen_at", "promotion_visitors", ["last_seen_at"]
    )
    op.create_index(
        "ix_promotion_visitors_tenant_last_seen",
        "promotion_visitors",
        ["tenant_id", "last_seen_at"],
    )

    for table in EVENT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("promotion_visitor_id", sa.BigInteger()))
            batch.create_foreign_key(
                f"fk_{table}_promotion_visitor_id",
                "promotion_visitors",
                ["promotion_visitor_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                f"ix_{table}_promotion_visitor_id", ["promotion_visitor_id"]
            )

    _backfill_visitors()
    for table in EVENT_TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET promotion_visitor_id = (
                    SELECT v.id
                    FROM promotion_visitors v
                    JOIN promotion_channels c ON c.created_by = v.tenant_id
                    WHERE c.id = {table}.channel_id
                      AND v.fingerprint_hash = {table}.visitor_fingerprint_hash
                    LIMIT 1
                )
                WHERE visitor_fingerprint_hash IS NOT NULL
                """
            )
        )

    op.drop_index("ix_promotion_events_channel_visitor", table_name="promotion_events")
    op.drop_index(
        "ix_promotion_events_channel_fingerprint", table_name="promotion_events"
    )
    with op.batch_alter_table("promotion_events") as batch:
        batch.drop_column("visitor_id")
        batch.drop_column("visitor_fingerprint_hash")
        batch.drop_column("fingerprint_version")
        batch.drop_column("fingerprint_quality")
        batch.create_index(
            "ix_promotion_events_channel_promotion_visitor",
            ["channel_id", "promotion_visitor_id"],
        )

    op.drop_index(
        "ix_promotion_integration_events_visitor_id",
        table_name="promotion_integration_events",
    )
    op.drop_index(
        "ix_promotion_integration_events_visitor_fingerprint_hash",
        table_name="promotion_integration_events",
    )
    with op.batch_alter_table("promotion_integration_events") as batch:
        batch.drop_column("visitor_id")
        batch.drop_column("visitor_fingerprint_hash")
        batch.drop_column("fingerprint_version")
        batch.drop_column("fingerprint_quality")

    op.drop_index(
        "ix_account_pairing_attempts_visitor_id",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_channel_visitor_created",
        table_name="account_pairing_attempts",
    )
    op.drop_index(
        "ix_account_pairing_attempts_channel_fingerprint_created",
        table_name="account_pairing_attempts",
    )
    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.drop_column("visitor_id")
        batch.drop_column("visitor_fingerprint_hash")
        batch.drop_column("fingerprint_version")
        batch.drop_column("fingerprint_quality")
        batch.create_index(
            "ix_account_pairing_attempts_channel_promotion_visitor_created",
            ["channel_id", "promotion_visitor_id", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("account_pairing_attempts") as batch:
        batch.drop_index(
            "ix_account_pairing_attempts_channel_promotion_visitor_created"
        )
    with op.batch_alter_table("promotion_events") as batch:
        batch.drop_index("ix_promotion_events_channel_promotion_visitor")

    for table in EVENT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("visitor_id", sa.String(80)))
            batch.add_column(sa.Column("visitor_fingerprint_hash", sa.String(64)))
            batch.add_column(sa.Column("fingerprint_version", sa.String(40)))
            batch.add_column(sa.Column("fingerprint_quality", sa.String(16)))
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET visitor_id = CAST(promotion_visitor_id AS VARCHAR),
                    visitor_fingerprint_hash = (
                        SELECT fingerprint_hash FROM promotion_visitors
                        WHERE id = {table}.promotion_visitor_id
                    ),
                    fingerprint_version = (
                        SELECT fingerprint_version FROM promotion_visitors
                        WHERE id = {table}.promotion_visitor_id
                    ),
                    fingerprint_quality = (
                        SELECT fingerprint_quality FROM promotion_visitors
                        WHERE id = {table}.promotion_visitor_id
                    )
                WHERE promotion_visitor_id IS NOT NULL
                """
            )
        )
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_promotion_visitor_id")
            batch.drop_constraint(
                f"fk_{table}_promotion_visitor_id", type_="foreignkey"
            )
            batch.drop_column("promotion_visitor_id")

    op.create_index(
        "ix_promotion_events_channel_visitor",
        "promotion_events",
        ["channel_id", "visitor_id"],
    )
    op.create_index(
        "ix_promotion_events_channel_fingerprint",
        "promotion_events",
        ["channel_id", "visitor_fingerprint_hash"],
    )
    op.create_index(
        "ix_promotion_integration_events_visitor_id",
        "promotion_integration_events",
        ["visitor_id"],
    )
    op.create_index(
        "ix_promotion_integration_events_visitor_fingerprint_hash",
        "promotion_integration_events",
        ["visitor_fingerprint_hash"],
    )
    op.create_index(
        "ix_account_pairing_attempts_visitor_id",
        "account_pairing_attempts",
        ["visitor_id"],
    )
    op.create_index(
        "ix_account_pairing_attempts_channel_visitor_created",
        "account_pairing_attempts",
        ["channel_id", "visitor_id", "created_at"],
    )
    op.create_index(
        "ix_account_pairing_attempts_channel_fingerprint_created",
        "account_pairing_attempts",
        ["channel_id", "visitor_fingerprint_hash", "created_at"],
    )
    op.drop_table("promotion_visitors")
