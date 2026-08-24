from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AccountPairingAttempt,
    PersonalAccount,
    PromotionChannel,
    PromotionEvent,
    PromotionLead,
    PromotionVisitor,
)
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
    "pairing_interrupted": "gateway_failed",
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
    promotion_visitor: PromotionVisitor | None,
    reason_code: str,
    stage: str,
    traffic_source: str,
    source_ip: str | None = None,
    visitor_country_code: str | None = None,
    network_source: str | None = None,
    request_context: dict[str, Any] | None = None,
    detail_code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> PromotionEvent:
    """Persist one pre-attempt loss per identifiable source, reason and UTC day.

    Pairing attempts remain authoritative after an attempt row exists. This
    event covers only failures that happen before that row can be created.
    """

    canonical = canonical_pairing_failure_reason(reason_code)
    occurred_at = utcnow()
    if promotion_visitor is not None:
        subject = f"visitor:{promotion_visitor.id}"
    else:
        user_agent = str((request_context or {}).get("userAgent") or "")[:512]
        anonymous_source = f"{source_ip or 'unknown'}\n{user_agent}"
        subject = "anonymous:" + hashlib.sha256(
            anonymous_source.encode("utf-8")
        ).hexdigest()[:24]
    idempotency_key = (
        f"pairing_failed:{occurred_at.date().isoformat()}:{canonical}:{subject}"
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
        promotion_visitor_id=(
            promotion_visitor.id if promotion_visitor is not None else None
        ),
        occurred_at=occurred_at,
        country_code=channel.country_code,
        source_ip=source_ip,
        visitor_country_code=visitor_country_code,
        network_source=network_source,
        request_context_json=dict(request_context or {}),
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


def persist_pairing_attempt_failure_event(
    db: Session,
    *,
    channel: PromotionChannel,
    attempt: AccountPairingAttempt,
    account: PersonalAccount,
    reason_code: str,
    stage: str,
    provider_code: str | None = None,
    occurred_at: datetime | None = None,
) -> PromotionEvent:
    """Project one terminal pairing-attempt failure into promotion monitoring."""

    idempotency_key = f"pairing_failed:attempt:{attempt.id}"
    existing = db.scalar(
        select(PromotionEvent).where(
            PromotionEvent.channel_id == channel.id,
            PromotionEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing

    canonical = canonical_pairing_failure_reason(reason_code)
    traffic_source = (
        "fission"
        if account.source_ref_type == "promotion_channel_fission"
        else "direct"
    )
    lead = db.scalar(
        select(PromotionLead)
        .where(
            PromotionLead.channel_id == channel.id,
            PromotionLead.phone_e164 == account.phone_e164,
        )
        .order_by(PromotionLead.last_seen_at.desc())
        .limit(1)
    )
    metadata: dict[str, Any] = {
        "reasonCode": canonical,
        "reasonLabel": PAIRING_FAILURE_LABELS[canonical],
        "detailCode": reason_code,
        "stage": stage,
        "trafficSource": traffic_source,
        "attemptId": str(attempt.id),
        "accountId": str(account.id),
        "attemptType": attempt.attempt_type,
    }
    if provider_code:
        metadata["providerCode"] = provider_code
    event = PromotionEvent(
        public_id=new_public_id("pevt"),
        channel_id=channel.id,
        event_type="pairing_failed",
        idempotency_key=idempotency_key,
        promotion_visitor_id=attempt.promotion_visitor_id,
        lead_id=lead.id if lead is not None else None,
        occurred_at=occurred_at or utcnow(),
        country_code=channel.country_code,
        source_ip=attempt.source_ip,
        visitor_country_code=attempt.visitor_country_code,
        network_source=attempt.network_source,
        request_context_json=dict(attempt.request_context_json or {}),
        metadata_json=metadata,
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        duplicate = db.scalar(
            select(PromotionEvent).where(
                PromotionEvent.channel_id == channel.id,
                PromotionEvent.idempotency_key == idempotency_key,
            )
        )
        if duplicate is None:
            raise
        return duplicate
    return event
