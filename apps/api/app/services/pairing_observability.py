from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PromotionChannel, PromotionEvent
from app.security import utcnow
from app.snowflake import new_public_id


PAIRING_FAILURE_LABELS = {
    "invalid_phone": "号码无效",
    "invalid_request": "请求信息无效",
    "number_unavailable": "号码不可用",
    "pairing_in_progress": "号码正在配对",
    "rate_limited": "请求限速",
    "protocol_unavailable": "协议节点不可用",
    "configuration_unavailable": "渠道配置不可用",
    "connection_route_unavailable": "连接线路不可用",
    "gateway_failed": "网关失败",
    "pairing_expired": "配对码过期",
    "pairing_cancelled": "用户取消",
    "service_unavailable": "服务暂时不可用",
    "unknown": "其他失败",
}

PAIRING_FAILURE_ALIASES = {
    "invalid_phone": "invalid_phone",
    "device_identity_invalid": "invalid_request",
    "invalid_request": "invalid_request",
    "number_unavailable": "number_unavailable",
    "account_already_linked": "number_unavailable",
    "pairing_in_progress": "pairing_in_progress",
    "rate_limited": "rate_limited",
    "protocol_unavailable": "protocol_unavailable",
    "protocol_capacity_limited": "protocol_unavailable",
    "channel_configuration_unavailable": "configuration_unavailable",
    "configuration_unavailable": "configuration_unavailable",
    "connection_route_unavailable": "connection_route_unavailable",
    "gateway_failed": "gateway_failed",
    "pairing_start_failed": "gateway_failed",
    "pairing_failed": "gateway_failed",
    "pairing_connection_lost": "gateway_failed",
    "connection_lost": "gateway_failed",
    "protocol_disconnect": "gateway_failed",
    "credential_store_failure": "gateway_failed",
    "logged_out": "gateway_failed",
    "bad_session": "gateway_failed",
    "multidevice_mismatch": "gateway_failed",
    "restricted": "gateway_failed",
    "failed": "gateway_failed",
    "pairing_expired": "pairing_expired",
    "expired": "pairing_expired",
    "pairing_cancelled": "pairing_cancelled",
    "cancelled": "pairing_cancelled",
    "service_temporarily_unavailable": "service_unavailable",
    "service_unavailable": "service_unavailable",
}


def canonical_pairing_failure_reason(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return PAIRING_FAILURE_ALIASES.get(normalized, "unknown")


def pairing_failure_label(value: str | None) -> str:
    return PAIRING_FAILURE_LABELS[canonical_pairing_failure_reason(value)]


def persist_pairing_failure_event(
    db: Session,
    *,
    channel: PromotionChannel,
    visitor_id: str,
    reason_code: str,
    stage: str,
    traffic_source: str,
    fingerprint_hash: str | None = None,
    fingerprint_version: str | None = None,
    fingerprint_quality: str | None = None,
    detail_code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> PromotionEvent:
    """Persist one pre-attempt loss per visitor, reason and UTC day.

    Pairing attempts remain authoritative after an attempt row exists. This
    event covers only failures that happen before that row can be created.
    """

    canonical = canonical_pairing_failure_reason(reason_code)
    occurred_at = utcnow()
    subject = fingerprint_hash or visitor_id
    subject_digest = hashlib.sha256(subject.encode()).hexdigest()[:24]
    idempotency_key = (
        f"pairing_failed:{occurred_at.date().isoformat()}:{canonical}:"
        f"{subject_digest}"
    )
    existing = db.scalar(
        select(PromotionEvent).where(
            PromotionEvent.channel_id == channel.id,
            PromotionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    metadata = {
        "reasonCode": canonical,
        "reasonLabel": PAIRING_FAILURE_LABELS[canonical],
        "detailCode": detail_code or reason_code,
        "stage": stage,
        "trafficSource": traffic_source,
    }
    if extra:
        metadata.update(extra)
    event = PromotionEvent(
        public_id=new_public_id("pevt"),
        channel_id=channel.id,
        event_type="pairing_failed",
        idempotency_key=idempotency_key,
        visitor_id=visitor_id,
        visitor_fingerprint_hash=fingerprint_hash,
        fingerprint_version=fingerprint_version,
        fingerprint_quality=fingerprint_quality,
        occurred_at=occurred_at,
        country_code=channel.country_code,
        metadata_json=metadata,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(PromotionEvent).where(
                PromotionEvent.channel_id == channel.id,
                PromotionEvent.idempotency_key == idempotency_key,
            )
        )
    return event
