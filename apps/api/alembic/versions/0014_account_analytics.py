"""Add promotion fee rate and durable account lifecycle events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision: str = "0014_account_analytics"
down_revision: str | None = "0013_protocol_nodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    started_at = datetime.now(UTC)
    with op.batch_alter_table("ad_metrics") as batch:
        batch.add_column(
            sa.Column(
                "ad_fee_rate",
                sa.Numeric(9, 4),
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "account_analytics_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_account_analytics_state_singleton"),
    )
    analytics_state = sa.table(
        "account_analytics_state",
        sa.column("id", sa.Integer()),
        sa.column("collection_started_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        analytics_state.insert().values(id=1, collection_started_at=started_at)
    )
    op.create_table(
        "account_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(80), nullable=False, unique=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("personal_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(32)),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("reason_category", sa.String(64)),
        sa.Column("provider_code", sa.String(64)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "account_id", "public_id", name="uq_account_lifecycle_account_event"
        ),
    )
    op.create_index(
        "ix_account_lifecycle_events_account_occurred",
        "account_lifecycle_events",
        ["account_id", "occurred_at"],
    )
    op.create_index(
        "ix_account_lifecycle_events_to_state",
        "account_lifecycle_events",
        ["to_state"],
    )
    bind = op.get_bind()
    accounts = sa.table(
        "personal_accounts",
        sa.column("id", sa.Integer()),
        sa.column("public_id", sa.String()),
        sa.column("status", sa.String()),
    )
    events = sa.table(
        "account_lifecycle_events",
        sa.column("public_id", sa.String()),
        sa.column("account_id", sa.Integer()),
        sa.column("from_state", sa.String()),
        sa.column("to_state", sa.String()),
        sa.column("reason_category", sa.String()),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
    )
    for account_id, public_id, account_status in bind.execute(
        sa.select(accounts.c.id, accounts.c.public_id, accounts.c.status)
    ):
        bind.execute(
            events.insert().values(
                public_id=f"baseline_{public_id}",
                account_id=account_id,
                from_state=None,
                to_state=account_status,
                reason_category="analytics_baseline",
                occurred_at=started_at,
            )
        )


def downgrade() -> None:
    op.drop_table("account_lifecycle_events")
    op.drop_table("account_analytics_state")
    with op.batch_alter_table("ad_metrics") as batch:
        batch.drop_column("ad_fee_rate")
