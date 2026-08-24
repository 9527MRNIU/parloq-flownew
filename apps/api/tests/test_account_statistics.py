from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import (
    AccountAnalyticsState,
    AccountLifecycleEvent,
    MessageDelivery,
    PersonalAccount,
    ProtocolDefinition,
    ProtocolNode,
    UserAccount,
    UserGroup,
)
from app.security import hash_password
from app.services.account_statistics import LifecyclePoint, _snapshot_at


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_imported_linked_offline_is_not_valid_until_connected() -> None:
    imported_at = datetime(2026, 8, 12, 1, tzinfo=UTC)
    imported = LifecyclePoint(
        state="linked_offline",
        reason="session_imported",
        occurred_at=imported_at,
        event_id=1,
    )
    connected = LifecyclePoint(
        state="online_idle",
        reason="connected",
        occurred_at=imported_at + timedelta(minutes=2),
        event_id=2,
    )
    _, verified_before_connect = _snapshot_at(
        [imported, connected], imported_at + timedelta(minutes=1)
    )
    state_after_connect, verified_after_connect = _snapshot_at(
        [imported, connected], imported_at + timedelta(minutes=3)
    )
    assert verified_before_connect is False
    assert state_after_connect == connected
    assert verified_after_connect is True


def _utc_on(day, hour: int) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=SHANGHAI).astimezone(UTC)


def _make_operator(db, username: str) -> UserAccount:
    group = db.scalar(select(UserGroup).where(UserGroup.system_key == "operator"))
    assert group is not None
    user = UserAccount(
        username=username,
        display_name=username,
        group_id=group.id,
        password_hash=hash_password("stats-password-123"),
        role="operator",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _event(
    db,
    account: PersonalAccount,
    public_id: str,
    from_state: str | None,
    to_state: str,
    occurred_at: datetime,
    reason: str,
) -> None:
    db.add(
        AccountLifecycleEvent(
            public_id=public_id,
            account_id=account.id,
            from_state=from_state,
            to_state=to_state,
            reason_category=reason,
            occurred_at=occurred_at,
        )
    )


def test_account_statistics_are_event_based_and_tenant_scoped(
    admin_client: TestClient,
) -> None:
    today = datetime.now(SHANGHAI).date()
    first_day = today - timedelta(days=2)
    event_day = today - timedelta(days=1)
    collection_start = _utc_on(first_day, 6)

    with SessionLocal() as db:
        state = db.scalar(
            select(AccountAnalyticsState).where(
                AccountAnalyticsState.singleton_key == "global"
            )
        )
        assert state is not None
        original_collection_start = state.collection_started_at
        state.collection_started_at = collection_start

        owner = _make_operator(db, "account-stats-owner")
        other = _make_operator(db, "account-stats-other")
        protocol_definition = db.scalar(
            select(ProtocolDefinition).where(ProtocolDefinition.is_builtin.is_(True))
        )
        assert protocol_definition is not None
        owner_protocol = ProtocolNode(
            public_id="protocol_account_stats_owner",
            name="Account statistics owner",
            protocol_definition_id=protocol_definition.id,
            created_by=owner.id,
        )
        other_protocol = ProtocolNode(
            public_id="protocol_account_stats_other",
            name="Account statistics other",
            protocol_definition_id=protocol_definition.id,
            created_by=other.id,
        )
        db.add_all((owner_protocol, other_protocol))
        db.flush()

        retained = PersonalAccount(
            public_id="wa_account_stats_retained",
            name="Retained then invalid",
            phone_e164="+12025550881",
            country_code="US",
            status="restricted",
            source="json_import",
            validation_status="ready",
            metadata_sync_status="pending",
            protocol_id=owner_protocol.id,
            enabled=True,
            created_by=owner.id,
            created_at=_utc_on(first_day - timedelta(days=1), 10),
        )
        same_day = PersonalAccount(
            public_id="wa_account_stats_same_day",
            name="New then invalid",
            phone_e164="+442079460881",
            country_code="GB",
            status="restricted",
            source="landing_page",
            validation_status="ready",
            metadata_sync_status="pending",
            protocol_id=owner_protocol.id,
            enabled=True,
            created_by=owner.id,
            created_at=_utc_on(event_day, 1),
        )
        foreign = PersonalAccount(
            public_id="wa_account_stats_foreign",
            name="Foreign tenant",
            phone_e164="+61255500881",
            country_code="AU",
            status="online_idle",
            source="landing_page",
            validation_status="ready",
            metadata_sync_status="pending",
            protocol_id=other_protocol.id,
            enabled=True,
            created_by=other.id,
            created_at=_utc_on(first_day, 8),
        )
        db.add_all((retained, same_day, foreign))
        db.flush()

        _event(
            db,
            retained,
            "stats_retained_baseline",
            None,
            "linked_offline",
            collection_start,
            "analytics_baseline",
        )
        _event(
            db,
            retained,
            "stats_retained_restricted",
            "linked_offline",
            "restricted",
            _utc_on(event_day, 12),
            "restricted",
        )
        _event(
            db,
            same_day,
            "stats_same_day_initial",
            None,
            "online_idle",
            _utc_on(event_day, 1),
            "landing_linked",
        )
        _event(
            db,
            same_day,
            "stats_same_day_restricted",
            "online_idle",
            "restricted",
            _utc_on(event_day, 10),
            "restricted",
        )
        _event(
            db,
            foreign,
            "stats_foreign_initial",
            None,
            "online_idle",
            _utc_on(first_day, 8),
            "landing_linked",
        )
        db.add(
            MessageDelivery(
                public_id="msg_account_stats_marketing",
                request_id="req_account_stats_marketing",
                account_id=retained.id,
                recipient_e164="+12025550882",
                status="sent",
                queued_at=_utc_on(event_day, 7),
                sent_at=_utc_on(event_day, 8),
            )
        )
        db.commit()

    owner_client = TestClient(app)
    try:
        login = owner_client.post(
            "/api/auth/login",
            json={
                "username": "account-stats-owner",
                "password": "stats-password-123",
            },
        )
        assert login.status_code == 200

        overview = owner_client.get("/api/account-statistics/overview")
        assert overview.status_code == 200, overview.text
        summary = overview.json()["data"]
        assert summary["totalAccounts"] == 2
        assert summary["validAccounts"] == 0
        assert summary["validRate"] == 0
        assert summary["onlineAccounts"] == 0
        assert summary["onlineRate"] is None
        assert summary["invalidAccounts"] == 2
        assert summary["invalidRate"] == 1
        assert summary["countryCount"] == 2

        daily = owner_client.get(
            "/api/account-statistics/daily",
            params={"dateFrom": first_day.isoformat(), "dateTo": today.isoformat()},
        )
        assert daily.status_code == 200, daily.text
        payload = daily.json()["data"]
        assert payload["timezone"] == "Asia/Shanghai"
        assert len(payload["rows"]) == 3
        assert payload["rows"][0]["isPartial"] is True
        event_row = payload["rows"][1]
        assert event_row["date"] == event_day.isoformat()
        assert event_row["source"] == "historical"
        assert event_row["totalAccounts"] == 2
        assert event_row["retainedAccounts"] == 1
        assert event_row["newAccounts"] == 1
        assert event_row["newInvalidAccounts"] == 1
        assert event_row["newInvalidRate"] == 1
        assert event_row["invalidatedAccounts"] == 2
        assert event_row["preMarketingInvalid"] == 1
        assert event_row["preMarketingInvalidRate"] == 0.5
        assert event_row["postMarketingInvalid"] == 1
        assert event_row["postMarketingInvalidRate"] == 0.5
        assert event_row["netGrowth"] == -1
        assert event_row["overallInvalidRate"] == 1

        countries = owner_client.get("/api/account-statistics/countries")
        assert countries.status_code == 200
        country_rows = {
            row["countryCode"]: row for row in countries.json()["data"]["rows"]
        }
        assert set(country_rows) == {"GB", "US"}
        assert country_rows["US"]["invalidAccounts"] == 1
        assert country_rows["US"]["validRate"] == 0

        empty = owner_client.get(
            "/api/account-statistics/daily",
            params={
                "dateFrom": event_day.isoformat(),
                "dateTo": event_day.isoformat(),
                "countryCode": "CA",
            },
        )
        empty_row = empty.json()["data"]["rows"][0]
        assert empty_row["onlineRate"] is None
        assert empty_row["newInvalidRate"] is None
        assert empty_row["overallInvalidRate"] is None

        too_long = owner_client.get(
            "/api/account-statistics/daily",
            params={
                "dateFrom": (today - timedelta(days=90)).isoformat(),
                "dateTo": today.isoformat(),
            },
        )
        assert too_long.status_code == 422
    finally:
        owner_client.close()
        with SessionLocal() as db:
            state = db.scalar(
                select(AccountAnalyticsState).where(
                    AccountAnalyticsState.singleton_key == "global"
                )
            )
            assert state is not None
            state.collection_started_at = original_collection_start
            db.commit()
