from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DomainRecord, UserAccount
from app.security import utcnow
from app.services import domain_onboarding_worker
from app.snowflake import new_public_id


def test_waiting_domain_onboarding_continues_in_background(
    admin_client,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def complete(db, item: DomainRecord) -> DomainRecord:
        calls.append(item.hostname)
        item.onboarding_status = "completed"
        item.onboarding_stage = "completed"
        item.onboarding_message = "域名已自动接入并通过公网验证"
        item.onboarding_completed_at = utcnow()
        db.commit()
        db.refresh(item)
        return item

    monkeypatch.setattr(
        domain_onboarding_worker,
        "continue_domain_onboarding",
        complete,
    )

    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        item = DomainRecord(
            public_id=new_public_id("dom"),
            hostname="background-onboarding.example",
            acquisition_type="purchased",
            management_mode="platform",
            registrar_provider="namesilo",
            registration_status="active",
            hosting_provider="cloudflare",
            hosting_status="pending",
            verification_token="background-onboarding-proof",
            enabled=True,
            onboarding_status="waiting",
            onboarding_stage="registrar_nameservers",
            onboarding_attempted_at=utcnow() - timedelta(seconds=10),
            created_by=admin.id,
        )
        db.add(item)
        db.commit()
        domain_id = item.id

        assert domain_onboarding_worker.process_domain_onboarding_once(db, limit=1) == 1
        db.refresh(item)
        assert item.onboarding_status == "completed"
        assert item.onboarding_stage == "completed"
        assert calls == ["background-onboarding.example"]

        db.delete(item)
        db.commit()

    with SessionLocal() as db:
        assert db.get(DomainRecord, domain_id) is None


def test_recent_waiting_domain_is_not_retried_too_fast(
    admin_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        domain_onboarding_worker,
        "continue_domain_onboarding",
        lambda _db, _item: (_ for _ in ()).throw(
            AssertionError("recent domain must not be claimed")
        ),
    )

    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        item = DomainRecord(
            public_id=new_public_id("dom"),
            hostname="recent-background-onboarding.example",
            acquisition_type="purchased",
            management_mode="platform",
            registrar_provider="namesilo",
            registration_status="active",
            hosting_provider="cloudflare",
            hosting_status="pending",
            verification_token="recent-background-onboarding-proof",
            enabled=True,
            onboarding_status="waiting",
            onboarding_stage="registrar_nameservers",
            onboarding_attempted_at=utcnow(),
            created_by=admin.id,
        )
        db.add(item)
        db.commit()

        assert domain_onboarding_worker.process_domain_onboarding_once(db, limit=1) == 0

        db.delete(item)
        db.commit()


def test_connected_domain_remains_manual(
    admin_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        domain_onboarding_worker,
        "continue_domain_onboarding",
        lambda _db, _item: (_ for _ in ()).throw(
            AssertionError("connected domain must remain manual")
        ),
    )

    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        item = DomainRecord(
            public_id=new_public_id("dom"),
            hostname="manual-connected-domain.example",
            acquisition_type="connected",
            management_mode="external",
            registration_status="active",
            hosting_provider="cloudflare",
            hosting_status="pending",
            verification_token="manual-connected-domain-proof",
            enabled=True,
            onboarding_status="waiting",
            onboarding_stage="cloudflare_zone",
            onboarding_attempted_at=utcnow() - timedelta(seconds=10),
            created_by=admin.id,
        )
        db.add(item)
        db.commit()

        assert domain_onboarding_worker.process_domain_onboarding_once(db, limit=1) == 0
        db.refresh(item)
        assert item.onboarding_status == "waiting"

        db.delete(item)
        db.commit()
