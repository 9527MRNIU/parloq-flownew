from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountLifecycleEvent, PersonalAccount
from app.security import utcnow


def record_initial_account_state(
    db: Session,
    account: PersonalAccount,
    *,
    reason_category: str,
) -> AccountLifecycleEvent:
    """Create the durable first state used by account-pool analytics.

    Account creation and the lifecycle event live in the caller's transaction,
    so statistics never observe an account without a starting state.
    """

    event_id = f"initial_{account.public_id}"
    existing = db.scalar(
        select(AccountLifecycleEvent).where(
            AccountLifecycleEvent.public_id == event_id
        )
    )
    if existing is not None:
        return existing
    event = AccountLifecycleEvent(
        public_id=event_id,
        account_id=account.id,
        from_state=None,
        to_state=account.status,
        reason_category=reason_category,
        occurred_at=account.created_at or utcnow(),
    )
    db.add(event)
    return event
