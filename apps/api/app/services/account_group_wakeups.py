from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AccountGroupWakeupEvent, HyperlinkTask
from app.security import utcnow
from app.task_queue import enqueue_hyperlink_task


logger = logging.getLogger("parloq.account-group-wakeups")


def record_group_wakeup(
    db,
    group_id: int | None,
    *,
    reason: str,
    account_id: int | None = None,
) -> AccountGroupWakeupEvent | None:
    """Write an account-pool change into the caller's database transaction."""

    if group_id is None:
        return None
    event = AccountGroupWakeupEvent(
        group_id=group_id,
        account_id=account_id,
        reason=reason[:64],
    )
    db.add(event)
    return event


def dispatch_pending_group_wakeups(
    *, group_id: int | None = None, limit: int = 200
) -> tuple[int, int]:
    """Turn durable group events into idempotent Redis task wakeups.

    Events are marked processed only after all affected tasks were accepted by
    the queue layer. If Redis is unavailable, the transaction rolls back and a
    later worker pass retries the same events.
    """

    if get_settings().task_queue_mock:
        return 0, 0
    with SessionLocal() as db:
        statement = select(AccountGroupWakeupEvent).where(
            AccountGroupWakeupEvent.processed_at.is_(None)
        )
        if group_id is not None:
            statement = statement.where(
                AccountGroupWakeupEvent.group_id == group_id
            )
        statement = (
            statement.order_by(
                AccountGroupWakeupEvent.created_at,
                AccountGroupWakeupEvent.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(db.scalars(statement).all())
        if not events:
            return 0, 0

        group_ids = sorted({event.group_id for event in events})
        task_ids = list(
            db.scalars(
                select(HyperlinkTask.id).where(
                    HyperlinkTask.account_group_id.in_(group_ids),
                    HyperlinkTask.sender_mode == "dynamic_group",
                    HyperlinkTask.status.in_(("running", "waiting_accounts")),
                )
            ).all()
        )
        for task_id in task_ids:
            enqueue_hyperlink_task(str(task_id))

        processed_at = utcnow()
        for event in events:
            event.processed_at = processed_at
        db.commit()
        return len(events), len(task_ids)


def dispatch_group_wakeups_best_effort(group_id: int | None = None) -> None:
    """Reduce wakeup latency while keeping the database outbox authoritative."""

    if group_id is None:
        return
    try:
        dispatch_pending_group_wakeups(group_id=group_id)
    except Exception:
        logger.exception(
            "account_group_wakeup_dispatch_failed",
            extra={"account_group_id": str(group_id)},
        )
