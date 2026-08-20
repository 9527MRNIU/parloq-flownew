from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, object_session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    MetaConversionDelivery,
    MetaPixel,
    PromotionChannel,
    PromotionEvent,
)
from app.security import decrypt_secret, utcnow
from app.snowflake import new_public_id


DEFAULT_META_EVENT_MAPPING: dict[str, str] = {
    "page_view": "PageView",
    "phone_submit": "Lead",
    "pairing_started": "InitiateCheckout",
    "pairing_verified": "CompleteRegistration",
}
META_EVENT_KEYS = tuple(DEFAULT_META_EVENT_MAPPING)
META_STANDARD_EVENTS = {
    "PageView",
    "ViewContent",
    "Search",
    "AddToCart",
    "AddToWishlist",
    "InitiateCheckout",
    "AddPaymentInfo",
    "Purchase",
    "Lead",
    "CompleteRegistration",
    "Contact",
    "Subscribe",
}


def normalized_meta_event_mapping(value: dict | None) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, str] = {}
    for key, default in DEFAULT_META_EVENT_MAPPING.items():
        raw = source.get(key, default)
        if raw in {None, "", "disabled"}:
            result[key] = ""
        elif isinstance(raw, str) and raw in META_STANDARD_EVENTS:
            result[key] = raw
        else:
            result[key] = default
    return result


def browser_event_descriptor(
    channel: PromotionChannel,
    event_key: str,
    event_id: str,
) -> dict[str, str] | None:
    session = object_session(channel)
    pixel = session.get(MetaPixel, channel.pixel_id) if session and channel.pixel_id else None
    if pixel is None or not pixel.enabled or not pixel.browser_pixel_enabled:
        return None
    event_name = normalized_meta_event_mapping(
        pixel.event_mapping_json
    ).get(event_key)
    if not event_name:
        return None
    return {"name": event_name, "eventId": event_id}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_cookie(value: Any, pattern: str) -> str | None:
    text = str(value or "").strip()
    return text if text and len(text) <= 255 and re.fullmatch(pattern, text) else None


def _request_user_data(
    request: Request,
    *,
    phone: str | None,
    visitor_id: str | None,
) -> dict[str, Any]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    client_ip = forwarded or (request.client.host if request.client else "")
    user_agent = request.headers.get("user-agent", "")[:1000]
    result: dict[str, Any] = {}
    if client_ip:
        result["client_ip_address"] = client_ip[:64]
    if user_agent:
        result["client_user_agent"] = user_agent
    fbp = _safe_cookie(request.cookies.get("_fbp"), r"fb\.\d+\.\d+\.[A-Za-z0-9_-]+")
    fbc = _safe_cookie(request.cookies.get("_fbc"), r"fb\.\d+\.\d+\.[A-Za-z0-9_-]+")
    if fbp:
        result["fbp"] = fbp
    if fbc:
        result["fbc"] = fbc
    if phone:
        normalized_phone = "".join(char for char in phone if char.isdigit())
        if normalized_phone:
            result["ph"] = [_sha256(normalized_phone)]
    if visitor_id:
        result["external_id"] = [_sha256(visitor_id.strip().lower())]
    return result


def enqueue_meta_conversion(
    db: Session,
    *,
    channel: PromotionChannel,
    event_key: str,
    event_id: str,
    event_time,
    request: Request,
    promotion_event: PromotionEvent | None = None,
    phone: str | None = None,
    visitor_id: str | None = None,
    custom_data: dict | None = None,
) -> MetaConversionDelivery | None:
    if not channel.pixel_id:
        return None
    pixel = db.get(MetaPixel, channel.pixel_id)
    if (
        pixel is None
        or not pixel.enabled
        or not pixel.capi_enabled
        or not pixel.capi_token_ciphertext
    ):
        return None
    event_name = normalized_meta_event_mapping(
        pixel.event_mapping_json
    ).get(event_key)
    if not event_name:
        return None
    source_url = str(request.url.replace(query=""))[:2000]
    delivery = MetaConversionDelivery(
        public_id=new_public_id("mcapi"),
        channel_id=channel.id,
        pixel_id=pixel.id,
        promotion_event_id=promotion_event.id if promotion_event else None,
        event_name=event_name,
        event_id=event_id,
        event_time=event_time,
        action_source="website",
        event_source_url=source_url,
        user_data_json=_request_user_data(
            request, phone=phone, visitor_id=visitor_id
        ),
        custom_data_json=custom_data or {},
        status="pending",
        next_attempt_at=utcnow(),
    )
    db.add(delivery)
    return delivery


def _provider_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)[:500]
        message = payload.get("message")
        if message:
            return str(message)[:500]
    return f"Meta CAPI 返回 HTTP {response.status_code}"


def probe_meta_conversion(
    *,
    channel: PromotionChannel,
    pixel: MetaPixel,
    request: Request,
    event_source_url: str,
) -> dict[str, Any]:
    """Send one isolated CAPI probe without creating a delivery-ledger row."""
    if (
        not pixel.enabled or not pixel.capi_enabled or not pixel.capi_token_ciphertext
    ):
        raise ValueError("Meta Pixel 已停用或缺少 CAPI Token")

    event_name = "ParloqCapiProbe"
    event_id = f"parloq-probe-{uuid4().hex}"
    payload = {
        "data": [
            {
                "event_name": event_name,
                "event_time": int(utcnow().timestamp()),
                "event_id": event_id,
                "action_source": "website",
                "event_source_url": event_source_url[:2000],
                "user_data": _request_user_data(
                    request,
                    phone=None,
                    visitor_id=f"capi-probe:{channel.id}:{event_id}",
                ),
                "custom_data": {"probe": True},
            }
        ]
    }
    result: dict[str, Any] = {
        "ok": False,
        "datasetId": pixel.dataset_id,
        "eventName": event_name,
        "eventId": event_id,
        "providerTraceId": "",
        "httpStatus": None,
        "sendError": "",
    }
    settings = get_settings()
    if settings.meta_capi_mock:
        return {
            **result,
            "ok": True,
            "providerTraceId": "mock-probe",
            "httpStatus": 200,
        }

    try:
        token = decrypt_secret(pixel.capi_token_ciphertext)
        response = httpx.post(
            f"{settings.meta_capi_base_url}/{settings.meta_capi_api_version}/{pixel.dataset_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=15.0,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {**result, "sendError": str(exc)[:500]}

    result["httpStatus"] = response.status_code
    if not response.is_success:
        result["sendError"] = _provider_error_message(response)
        return result
    try:
        response_payload = response.json() if response.content else {}
    except ValueError:
        response_payload = {}
    result["ok"] = True
    if isinstance(response_payload, dict):
        result["providerTraceId"] = str(
            response_payload.get("fbtrace_id") or ""
        )[:255]
    return result


def _claim_due_deliveries() -> list[int]:
    settings = get_settings()
    now = utcnow()
    stale = now - timedelta(minutes=5)
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(MetaConversionDelivery)
                .where(
                    or_(
                        MetaConversionDelivery.status.in_(("pending", "retry")),
                        (
                            (MetaConversionDelivery.status == "sending")
                            & (MetaConversionDelivery.last_attempt_at <= stale)
                        ),
                    ),
                    or_(
                        MetaConversionDelivery.next_attempt_at.is_(None),
                        MetaConversionDelivery.next_attempt_at <= now,
                    ),
                )
                .order_by(MetaConversionDelivery.next_attempt_at, MetaConversionDelivery.id)
                .limit(settings.meta_capi_batch_size)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for row in rows:
            row.status = "sending"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.last_attempt_at = now
            row.next_attempt_at = None
        db.commit()
        return [row.id for row in rows]


def _provider_payload(row: MetaConversionDelivery) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_name": row.event_name,
        "event_time": int(row.event_time.timestamp()),
        "event_id": row.event_id,
        "action_source": row.action_source,
        "user_data": row.user_data_json or {},
    }
    if row.event_source_url:
        event["event_source_url"] = row.event_source_url
    if row.custom_data_json:
        event["custom_data"] = row.custom_data_json
    return {"data": [event]}


def _deliver_one(delivery_id: int) -> str:
    settings = get_settings()
    with SessionLocal() as db:
        row = db.get(MetaConversionDelivery, delivery_id)
        if row is None or row.status != "sending":
            return "ignored"
        pixel = db.get(MetaPixel, row.pixel_id)
        if (
            pixel is None
            or not pixel.enabled
            or not pixel.capi_token_ciphertext
        ):
            row.status = "failed"
            row.last_error = "Meta Pixel 已停用或缺少 CAPI Token"
            db.commit()
            return "failed"
        if settings.meta_capi_mock:
            row.status = "delivered"
            row.delivered_at = utcnow()
            row.provider_trace_id = "mock"
            row.last_error = None
            db.commit()
            return "delivered"
        try:
            token = decrypt_secret(pixel.capi_token_ciphertext)
            response = httpx.post(
                f"{settings.meta_capi_base_url}/{settings.meta_capi_api_version}/{pixel.dataset_id}/events",
                headers={"Authorization": f"Bearer {token}"},
                json=_provider_payload(row),
                timeout=15.0,
            )
            response.raise_for_status()
            value = response.json() if response.content else {}
            row.status = "delivered"
            row.delivered_at = utcnow()
            row.provider_trace_id = str(value.get("fbtrace_id") or "")[:255] or None
            row.last_error = None
            db.commit()
            return "delivered"
        except (httpx.HTTPError, ValueError) as exc:
            retryable = row.attempt_count < settings.meta_capi_max_attempts
            row.status = "retry" if retryable else "failed"
            if retryable:
                delay = min(30 * (2 ** max(row.attempt_count - 1, 0)), 3600)
                row.next_attempt_at = utcnow() + timedelta(seconds=delay)
            row.last_error = str(exc)[:2000]
            db.commit()
            return row.status


def process_due_meta_conversions() -> dict[str, int]:
    counts = {"claimed": 0, "delivered": 0, "retry": 0, "failed": 0}
    identifiers = _claim_due_deliveries()
    counts["claimed"] = len(identifiers)
    for delivery_id in identifiers:
        result = _deliver_one(delivery_id)
        if result in counts:
            counts[result] += 1
    return counts
