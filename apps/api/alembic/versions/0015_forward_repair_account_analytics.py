"""Forward-repair account analytics state for early development databases.

Some development databases were stamped at 0014 while that migration was
still being iterated. Fresh databases already receive these objects in 0014;
this revision is deliberately idempotent and repairs only missing state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision: str = "0015_account_analytics_repair"
down_revision: str | None = "0014_account_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "account_analytics_state" not in inspector.get_table_names():
        op.create_table(
            "account_analytics_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "collection_started_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "id = 1", name="ck_account_analytics_state_singleton"
            ),
        )

    started_at = datetime.now(UTC)
    analytics_state = sa.table(
        "account_analytics_state",
        sa.column("id", sa.Integer()),
        sa.column("collection_started_at", sa.DateTime(timezone=True)),
    )
    if bind.execute(
        sa.select(analytics_state.c.id).where(analytics_state.c.id == 1)
    ).first() is None:
        bind.execute(
            analytics_state.insert().values(
                id=1, collection_started_at=started_at
            )
        )

    accounts = sa.table(
        "personal_accounts",
        sa.column("id", sa.Integer()),
        sa.column("public_id", sa.String()),
        sa.column("status", sa.String()),
    )
    events = sa.table(
        "account_lifecycle_events",
        sa.column("id", sa.Integer()),
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
        if bind.execute(
            sa.select(events.c.id).where(events.c.account_id == account_id).limit(1)
        ).first() is not None:
            continue
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
    # 0014 owns the objects. Removing repair data here would make the schema
    # inconsistent with 0014 and erase the collection boundary.
    pass
