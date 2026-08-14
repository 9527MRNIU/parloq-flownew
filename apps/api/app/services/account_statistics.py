from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountAnalyticsState,
    AccountLifecycleEvent,
    MessageDelivery,
    PersonalAccount,
    UserAccount,
)
from app.security import utcnow


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
VALID_STATES = {"linked_offline", "warming", "online_idle", "sending", "draining"}
ONLINE_STATES = {"online_idle", "sending"}


@dataclass(frozen=True)
class LifecyclePoint:
    state: str
    reason: str | None
    occurred_at: datetime
    event_id: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=REPORT_TIMEZONE).astimezone(UTC)


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 6) if total > 0 else None


def _is_invalidation(point: LifecyclePoint) -> bool:
    return point.state == "restricted" or (
        point.state == "unpaired" and point.reason == "logged_out"
    )


def _is_invalid_snapshot(point: LifecyclePoint | None) -> bool:
    return point is not None and _is_invalidation(point)


def _scope_accounts(statement, user: UserAccount):
    if user.role != "admin":
        statement = statement.where(PersonalAccount.created_by == user.id)
    return statement


def _latest_at(points: list[LifecyclePoint], cutoff: datetime) -> LifecyclePoint | None:
    latest = None
    for point in points:
        if point.occurred_at >= cutoff:
            break
        latest = point
    return latest


def _snapshot_at(
    points: list[LifecyclePoint], cutoff: datetime
) -> tuple[LifecyclePoint | None, bool]:
    """Return state plus whether that session has ever verified online.

    A creds-only import enters linked_offline before its first successful
    connection, so linked_offline alone is not evidence of a valid account.
    Migration baselines in a valid state represent an already-verified account.
    """

    latest = None
    verified = False
    for point in points:
        if point.occurred_at >= cutoff:
            break
        latest = point
        if point.state in ONLINE_STATES or point.reason == "connected":
            verified = True
        elif point.reason == "analytics_baseline":
            verified = point.state in VALID_STATES
        elif point.reason in {"session_imported", "pairing_started"}:
            verified = False
        elif _is_invalidation(point):
            verified = False
    return latest, verified


def _active_at(account: PersonalAccount, cutoff: datetime) -> bool:
    created_at = _as_utc(account.created_at)
    archived_at = _as_utc(account.archived_at) if account.archived_at else None
    return created_at < cutoff and (archived_at is None or archived_at >= cutoff)


def _collection_started_at(db: Session) -> datetime:
    state = db.scalar(
        select(AccountAnalyticsState).where(
            AccountAnalyticsState.singleton_key == "global"
        )
    )
    # A missing singleton means the migration has not established a trustworthy
    # history boundary. Starting at "now" is conservative and never invents old
    # snapshots from current account fields.
    return _as_utc(state.collection_started_at) if state else utcnow()


def _load_accounts(
    db: Session, user: UserAccount, country_code: str | None = None
) -> list[PersonalAccount]:
    statement = select(PersonalAccount)
    if country_code:
        statement = statement.where(PersonalAccount.country_code == country_code)
    return list(db.scalars(_scope_accounts(statement, user)).all())


def _load_lifecycle(
    db: Session, account_ids: list[int]
) -> dict[int, list[LifecyclePoint]]:
    grouped: dict[int, list[LifecyclePoint]] = defaultdict(list)
    if not account_ids:
        return grouped
    rows = db.scalars(
        select(AccountLifecycleEvent)
        .where(AccountLifecycleEvent.account_id.in_(account_ids))
        .order_by(
            AccountLifecycleEvent.account_id,
            AccountLifecycleEvent.occurred_at,
            AccountLifecycleEvent.id,
        )
    ).all()
    for item in rows:
        grouped[item.account_id].append(
            LifecyclePoint(
                state=item.to_state,
                reason=item.reason_category,
                occurred_at=_as_utc(item.occurred_at),
                event_id=item.id,
            )
        )
    return grouped


def _load_successful_marketing(
    db: Session, account_ids: list[int]
) -> dict[int, list[datetime]]:
    grouped: dict[int, list[datetime]] = defaultdict(list)
    if not account_ids:
        return grouped
    rows = db.scalars(
        select(MessageDelivery).where(
            MessageDelivery.account_id.in_(account_ids),
            MessageDelivery.status.in_(("sent", "delivered")),
        )
    ).all()
    for item in rows:
        sent_at = item.sent_at or item.delivered_at
        if sent_at is not None:
            grouped[item.account_id].append(_as_utc(sent_at))
    for values in grouped.values():
        values.sort()
    return grouped


def overview(db: Session, user: UserAccount) -> dict:
    accounts = [
        item
        for item in _load_accounts(db, user)
        if item.archived_at is None
    ]
    lifecycle = _load_lifecycle(db, [item.id for item in accounts])
    valid = 0
    online = 0
    invalid = 0
    for account in accounts:
        latest = lifecycle.get(account.id, [])[-1] if lifecycle.get(account.id) else None
        if account.validation_status == "ready" and account.status in VALID_STATES:
            valid += 1
        if account.validation_status == "ready" and account.status in ONLINE_STATES:
            online += 1
        if (
            account.validation_status == "failed"
            or account.status == "restricted"
            or (account.status == "unpaired" and _is_invalid_snapshot(latest))
        ):
            invalid += 1
    total = len(accounts)
    countries = {item.country_code for item in accounts if item.country_code}
    return {
        "totalAccounts": total,
        "validAccounts": valid,
        "validRate": _rate(valid, total),
        "onlineAccounts": online,
        "onlineRate": _rate(online, valid),
        "invalidAccounts": invalid,
        "invalidRate": _rate(invalid, total),
        "countryCount": len(countries),
        "collectionStartedAt": _collection_started_at(db).isoformat(),
    }


def countries(db: Session, user: UserAccount) -> list[dict]:
    accounts = [
        item
        for item in _load_accounts(db, user)
        if item.archived_at is None and item.country_code
    ]
    lifecycle = _load_lifecycle(db, [item.id for item in accounts])
    grouped: dict[str, list[PersonalAccount]] = defaultdict(list)
    for account in accounts:
        grouped[account.country_code or ""].append(account)
    rows = []
    for country_code, items in sorted(grouped.items()):
        valid = sum(
            item.validation_status == "ready" and item.status in VALID_STATES
            for item in items
        )
        online = sum(
            item.validation_status == "ready" and item.status in ONLINE_STATES
            for item in items
        )
        invalid = 0
        for item in items:
            points = lifecycle.get(item.id, [])
            latest = points[-1] if points else None
            if (
                item.validation_status == "failed"
                or item.status == "restricted"
                or (item.status == "unpaired" and _is_invalid_snapshot(latest))
            ):
                invalid += 1
        rows.append(
            {
                "countryCode": country_code,
                "countryName": country_code,
                "totalAccounts": len(items),
                "validAccounts": valid,
                "onlineAccounts": online,
                "invalidAccounts": invalid,
                "validRate": _rate(valid, len(items)),
            }
        )
    return rows


def daily(
    db: Session,
    user: UserAccount,
    *,
    date_from: date,
    date_to: date,
    country_code: str | None,
) -> tuple[list[dict], datetime]:
    collection_start = _collection_started_at(db)
    today = datetime.now(REPORT_TIMEZONE).date()
    effective_to = min(date_to, today)
    effective_from = max(date_from, collection_start.astimezone(REPORT_TIMEZONE).date())
    if effective_from > effective_to:
        return [], collection_start

    accounts = _load_accounts(db, user, country_code)
    account_ids = [item.id for item in accounts]
    lifecycle = _load_lifecycle(db, account_ids)
    marketing = _load_successful_marketing(db, account_ids)
    now = utcnow()
    rows: list[dict] = []
    cursor = effective_from
    while cursor <= effective_to:
        calendar_start = _day_start(cursor)
        calendar_end = _day_start(cursor + timedelta(days=1))
        window_start = max(calendar_start, collection_start)
        cutoff = min(calendar_end, now) if cursor == today else calendar_end

        active_end = [item for item in accounts if _active_at(item, cutoff)]
        retained = 0
        for account in accounts:
            if not _active_at(account, window_start):
                continue
            start_state = _latest_at(lifecycle.get(account.id, []), window_start)
            if not _is_invalid_snapshot(start_state):
                retained += 1

        new_accounts = [
            item
            for item in accounts
            if window_start <= _as_utc(item.created_at) < cutoff
        ]
        end_snapshots = {
            item.id: _snapshot_at(lifecycle.get(item.id, []), cutoff)
            for item in active_end
        }
        valid = sum(
            point is not None and point.state in VALID_STATES and verified
            for point, verified in end_snapshots.values()
        )
        online = sum(
            point is not None and point.state in ONLINE_STATES and verified
            for point, verified in end_snapshots.values()
        )

        invalidations: dict[int, LifecyclePoint] = {}
        for account in accounts:
            for point in lifecycle.get(account.id, []):
                if point.occurred_at >= cutoff:
                    break
                if point.occurred_at >= window_start and _is_invalidation(point):
                    invalidations.setdefault(account.id, point)
                    break

        new_ids = {item.id for item in new_accounts}
        new_invalid = sum(account_id in new_ids for account_id in invalidations)
        post_marketing_invalid = 0
        for account_id, invalidation in invalidations.items():
            if any(
                sent_at <= invalidation.occurred_at
                for sent_at in marketing.get(account_id, [])
            ):
                post_marketing_invalid += 1
        invalidated = len(invalidations)
        pre_marketing_invalid = invalidated - post_marketing_invalid
        rows.append(
            {
                "date": cursor.isoformat(),
                "source": "realtime" if cursor == today else "historical",
                "isPartial": window_start > calendar_start,
                "windowStartedAt": window_start.isoformat(),
                "totalAccounts": len(active_end),
                "validAccounts": valid,
                "onlineAccounts": online,
                "onlineRate": _rate(online, valid),
                "retainedAccounts": retained,
                "newAccounts": len(new_accounts),
                "newInvalidAccounts": new_invalid,
                "newInvalidRate": _rate(new_invalid, len(new_accounts)),
                "invalidatedAccounts": invalidated,
                "preMarketingInvalid": pre_marketing_invalid,
                "preMarketingInvalidRate": _rate(
                    pre_marketing_invalid, invalidated
                ),
                "postMarketingInvalid": post_marketing_invalid,
                "postMarketingInvalidRate": _rate(
                    post_marketing_invalid, invalidated
                ),
                "netGrowth": len(new_accounts) - invalidated,
                "overallInvalidRate": _rate(
                    invalidated, retained + len(new_accounts)
                ),
            }
        )
        cursor += timedelta(days=1)
    return rows, collection_start
