from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.models import DomainRecord
from app.security import utcnow
from app.services.domain_onboarding import continue_domain_onboarding


logger = logging.getLogger("parloq.domain-onboarding-worker")
DOMAIN_ONBOARDING_RETRY_DELAY = timedelta(seconds=5)
DOMAIN_ONBOARDING_RUNNING_LEASE = timedelta(minutes=5)


def process_domain_onboarding_once(db: Session, *, limit: int = 2) -> int:
    """Advance waiting domain onboarding records without user interaction.

    Each record is claimed atomically. A normal waiting result is retried after
    a short delay, while a crashed/stale running claim can be recovered later.
    Expected provider failures are converted to waiting/failed states by the
    onboarding service itself.
    """

    processed = 0
    for _ in range(max(0, min(int(limit), 10))):
        now = utcnow()
        retry_before = now - DOMAIN_ONBOARDING_RETRY_DELAY
        stale_before = now - DOMAIN_ONBOARDING_RUNNING_LEASE
        item = db.scalar(
            select(DomainRecord)
            .where(
                DomainRecord.enabled.is_(True),
                DomainRecord.acquisition_type == "purchased",
                DomainRecord.management_mode == "platform",
                or_(
                    and_(
                        DomainRecord.onboarding_status.in_(("idle", "waiting")),
                        or_(
                            DomainRecord.onboarding_attempted_at.is_(None),
                            DomainRecord.onboarding_attempted_at <= retry_before,
                        ),
                    ),
                    and_(
                        DomainRecord.onboarding_status == "running",
                        or_(
                            DomainRecord.onboarding_attempted_at.is_(None),
                            DomainRecord.onboarding_attempted_at <= stale_before,
                        ),
                    ),
                ),
            )
            .order_by(
                DomainRecord.onboarding_attempted_at.asc().nullsfirst(),
                DomainRecord.created_at.asc(),
                DomainRecord.id.asc(),
            )
            .limit(1)
        )
        if item is None:
            break
        previous_status = item.onboarding_status
        claimed = db.execute(
            update(DomainRecord)
            .where(
                DomainRecord.id == item.id,
                DomainRecord.onboarding_status == previous_status,
                or_(
                    DomainRecord.onboarding_attempted_at.is_(None),
                    DomainRecord.onboarding_attempted_at
                    <= (
                        stale_before
                        if previous_status == "running"
                        else retry_before
                    ),
                ),
            )
            .values(
                onboarding_status="running",
                onboarding_attempted_at=now,
                onboarding_message="后台正在核对平台配置",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.rollback()
            continue
        db.commit()
        db.refresh(item)
        try:
            continue_domain_onboarding(db, item)
        except Exception as exc:  # noqa: BLE001 - isolate one broken domain job
            db.rollback()
            persisted = db.get(DomainRecord, item.id)
            if persisted is not None:
                persisted.onboarding_status = "failed"
                persisted.onboarding_message = "后台自动接入发生异常，请检查服务日志"
                persisted.last_error = str(exc)[:1000]
                db.commit()
            logger.exception(
                "domain_onboarding_job_failed",
                extra={"domain_id": item.id},
            )
        processed += 1
    return processed
