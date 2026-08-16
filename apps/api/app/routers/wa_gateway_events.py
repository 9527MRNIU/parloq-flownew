from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AccountLifecycleEvent,
    AccountPairingAttempt,
    HyperlinkTask,
    HyperlinkTaskAccountSlot,
    HyperlinkTaskDelivery,
    MessageDelivery,
    PersonalAccount,
)
from app.routers.personal_accounts import delivery_row
from app.security import utcnow


router = APIRouter(prefix="/api/internal/wa-gateway", tags=["internal-wa-gateway"])

ACCOUNT_STATES = {
    "unpaired",
    "pairing",
    "linked_offline",
    "warming",
    "online_idle",
    "sending",
    "draining",
    "reauth_required",
    "restricted",
    "disabled",
    "validating",
}
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _account_state_event(payload: dict) -> dict:
    event_id = str(payload.get("eventId") or "").strip()
    account_public_id = str(payload.get("accountId") or "").strip()
    from_state_value = payload.get("fromState")
    from_state = (
        str(from_state_value).strip().lower()
        if from_state_value is not None
        else None
    )
    to_state = str(payload.get("toState") or "").strip().lower()
    reason = str(payload.get("reasonCategory") or "").strip().lower()
    provider_code = str(payload.get("providerCode") or "").strip() or None
    occurred_value = payload.get("occurredAt")

    if not EVENT_ID_RE.fullmatch(event_id):
        raise HTTPException(status_code=422, detail="eventId 无效")
    if not EVENT_ID_RE.fullmatch(account_public_id):
        raise HTTPException(status_code=422, detail="accountId 无效")
    if from_state is not None and from_state not in ACCOUNT_STATES:
        raise HTTPException(status_code=422, detail="fromState 无效")
    if to_state not in ACCOUNT_STATES:
        raise HTTPException(status_code=422, detail="toState 无效")
    if not REASON_RE.fullmatch(reason):
        raise HTTPException(status_code=422, detail="reasonCategory 无效")
    if provider_code is not None and not REASON_RE.fullmatch(provider_code):
        raise HTTPException(status_code=422, detail="providerCode 无效")
    if not isinstance(occurred_value, str) or len(occurred_value) > 64:
        raise HTTPException(status_code=422, detail="occurredAt 无效")
    try:
        occurred_at = datetime.fromisoformat(occurred_value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="occurredAt 无效") from None
    if occurred_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="occurredAt 必须包含时区")
    occurred_at = occurred_at.astimezone(UTC)
    if occurred_at > utcnow() + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="occurredAt 超出允许范围")

    with SessionLocal() as db:
        account = db.scalar(
            select(PersonalAccount).where(
                PersonalAccount.public_id == account_public_id
            )
        )
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        existing = db.scalar(
            select(AccountLifecycleEvent).where(
                AccountLifecycleEvent.public_id == event_id
            )
        )
        if existing is not None:
            if existing.account_id != account.id:
                raise HTTPException(status_code=409, detail="事件与账号不匹配")
            return {"data": {"ok": True, "duplicate": True, "eventId": event_id}}

        latest = db.scalar(
            select(AccountLifecycleEvent)
            .where(AccountLifecycleEvent.account_id == account.id)
            .order_by(
                AccountLifecycleEvent.occurred_at.desc(),
                AccountLifecycleEvent.id.desc(),
            )
            .limit(1)
        )
        item = AccountLifecycleEvent(
            public_id=event_id,
            account_id=account.id,
            from_state=from_state,
            to_state=to_state,
            reason_category=reason,
            provider_code=provider_code,
            occurred_at=occurred_at,
        )
        db.add(item)
        applied = latest is None or occurred_at >= latest.occurred_at.replace(
            tzinfo=latest.occurred_at.tzinfo or UTC
        )
        wakeup_group_id: int | None = None
        wakeup_task_ids: set[int] = set()
        if applied:
            account.status = to_state
            if to_state in {"online_idle", "sending"}:
                account.validation_status = "ready"
                account.last_connected_at = occurred_at
                account.last_error = None
                if account.group_id is not None:
                    from app.services.account_group_wakeups import (
                        record_group_wakeup,
                    )

                    record_group_wakeup(
                        db,
                        account.group_id,
                        reason="gateway_account_dispatchable",
                        account_id=account.id,
                    )
                    wakeup_group_id = account.group_id
            elif to_state == "restricted":
                account.last_error = "账号连接受到平台限制"
            elif to_state == "reauth_required":
                account.last_error = "账号会话需要重新验证"
            elif to_state == "unpaired" and reason in {
                "logged_out",
                "manual_logout",
                "pairing_failed",
                "pairing_connection_lost",
            }:
                account.validation_status = "failed"
                account.last_error = (
                    "配对连接已中断，请重新获取配对码"
                    if reason in {"pairing_failed", "pairing_connection_lost"}
                    else "账号会话已退出"
                )

            if to_state not in {"online_idle", "sending"}:
                affected_slots = list(
                    db.scalars(
                        select(HyperlinkTaskAccountSlot)
                        .join(
                            HyperlinkTask,
                            HyperlinkTask.id == HyperlinkTaskAccountSlot.task_id,
                        )
                        .where(
                            HyperlinkTaskAccountSlot.account_id == account.id,
                            HyperlinkTask.status.in_(
                                ("running", "waiting_accounts")
                            ),
                        )
                        .with_for_update()
                    ).all()
                )
                for slot in affected_slots:
                    for delivery_item in db.scalars(
                        select(HyperlinkTaskDelivery).where(
                            HyperlinkTaskDelivery.slot_id == slot.id,
                            HyperlinkTaskDelivery.submission_status == "leased",
                        )
                    ).all():
                        delivery_item.submission_status = "pending"
                        delivery_item.status = "queued"
                        delivery_item.account_id = None
                        delivery_item.slot_id = None
                        delivery_item.lease_token = None
                        delivery_item.leased_at = None
                        delivery_item.lease_expires_at = None
                        delivery_item.last_error = "发送账号状态异常，等待更换账号"
                    for delivery_item in db.scalars(
                        select(HyperlinkTaskDelivery).where(
                            HyperlinkTaskDelivery.slot_id == slot.id,
                            HyperlinkTaskDelivery.submission_status == "submitting",
                        )
                    ).all():
                        delivery_item.submission_status = "reconciling"
                        delivery_item.lease_token = None
                        delivery_item.lease_expires_at = None
                        delivery_item.last_error = "发送账号状态异常，等待核对提交结果"
                    wakeup_task_ids.add(slot.task_id)
                    slot.status = "vacant"
                    slot.account_id = None
                    slot.lease_token = None
                    slot.lease_expires_at = None
                    slot.released_at = occurred_at
                    slot.switch_count = int(slot.switch_count or 0) + 1
                    slot.consecutive_failure_count = 0
                    slot.last_switch_reason = f"account_state_{to_state}"[:64]
                    slot.last_error = account.last_error

            attempt = db.scalar(
                select(AccountPairingAttempt)
                .where(AccountPairingAttempt.account_id == account.id)
                .order_by(AccountPairingAttempt.created_at.desc())
                .limit(1)
            )
            if attempt is not None and attempt.status in {
                "code_issued",
                "waiting_phone",
                "reconnecting",
            }:
                if to_state in {"online_idle", "sending"}:
                    attempt.status = "verified"
                    attempt.verified_at = occurred_at
                    attempt.terminal_reason = None
                    attempt.provider_code = None
                    account.admission_status = "active"
                    from app.services.account_metadata_sync import (
                        enqueue_account_metadata_sync,
                    )

                    enqueue_account_metadata_sync(
                        db,
                        account,
                        sync_policy=attempt.sync_policy_json,
                        sync_policy_version=attempt.sync_policy_version,
                    )
                elif to_state == "unpaired" and reason in {
                    "pairing_expired",
                    "pairing_cancelled",
                    "pairing_failed",
                    "pairing_connection_lost",
                }:
                    attempt.status = {
                        "pairing_expired": "expired",
                        "pairing_cancelled": "cancelled",
                    }.get(reason, "failed")
                    attempt.terminal_reason = reason
                    attempt.provider_code = provider_code
                    if attempt.attempt_type == "initial":
                        account.admission_status = "abandoned"
        db.commit()
        if wakeup_group_id is not None:
            from app.services.account_group_wakeups import (
                dispatch_group_wakeups_best_effort,
            )

            dispatch_group_wakeups_best_effort(wakeup_group_id)
        if wakeup_task_ids:
            from app.task_queue import enqueue_hyperlink_task

            for wakeup_task_id in wakeup_task_ids:
                try:
                    enqueue_hyperlink_task(str(wakeup_task_id))
                except Exception:
                    # The durable 30-second recovery scan remains the fallback
                    # when Redis is temporarily unavailable.
                    pass
        return {
            "data": {
                "ok": True,
                "duplicate": False,
                "applied": applied,
                "eventId": event_id,
            }
        }


@router.post("/events")
async def receive_status_event(
    request: Request,
    x_parloq_signature: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if not settings.wa_gateway_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp 网关回调密钥未配置",
        )
    body = await request.body()
    if len(body) > 32 * 1024:
        raise HTTPException(status_code=413, detail="回调数据过大")
    expected = "sha256=" + hmac.new(
        settings.wa_gateway_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not x_parloq_signature or not hmac.compare_digest(
        x_parloq_signature, expected
    ):
        raise HTTPException(status_code=401, detail="回调签名无效")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="回调 JSON 无效") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="回调事件类型无效")
    if payload.get("event") == "account.state":
        return _account_state_event(payload)
    if payload.get("event") != "message.status":
        raise HTTPException(status_code=422, detail="回调事件类型无效")
    message_id = str(payload.get("messageId") or "").strip()
    next_status = str(payload.get("status") or "").strip().lower()
    if next_status == "read":
        next_status = "delivered"
    if not message_id or len(message_id) > 160:
        raise HTTPException(status_code=422, detail="messageId 无效")
    if next_status not in {"queued", "sent", "delivered", "failed"}:
        raise HTTPException(status_code=422, detail="消息状态无效")

    with SessionLocal() as db:
        delivery = db.scalar(
            select(MessageDelivery).where(MessageDelivery.public_id == message_id)
        )
        if delivery is None:
            # Compatibility for jobs accepted before messageId switched from the
            # client idempotency key to msg_<snowflake>.
            delivery = db.scalar(
                select(MessageDelivery).where(MessageDelivery.request_id == message_id)
            )
        if delivery is None:
            raise HTTPException(status_code=404, detail="消息记录不存在")
        account_id = str(payload.get("accountId") or "").strip()
        account = db.get(PersonalAccount, delivery.account_id)
        if account_id and (account is None or account.public_id != account_id):
            raise HTTPException(status_code=409, detail="消息与账号不匹配")

        duplicate = False
        current = delivery.status
        ranks = {"queued": 0, "sent": 1, "delivered": 2}
        if current == "failed" or (
            current == "delivered" and next_status == "failed"
        ):
            duplicate = True
        elif next_status == "failed":
            delivery.status = "failed"
            delivery.failed_at = delivery.failed_at or utcnow()
            error_code = str(payload.get("errorCode") or "").strip()
            delivery.last_error = error_code[:2000] or delivery.last_error
        elif ranks.get(next_status, -1) <= ranks.get(current, -1):
            duplicate = True
        else:
            now = utcnow()
            delivery.status = next_status
            if next_status in {"sent", "delivered"}:
                delivery.sent_at = delivery.sent_at or now
            if next_status == "delivered":
                delivery.delivered_at = delivery.delivered_at or now

        provider_id = str(payload.get("providerMessageId") or "").strip()
        if provider_id and not delivery.provider_message_id:
            delivery.provider_message_id = provider_id[:255]
        task_delivery = db.scalar(
            select(HyperlinkTaskDelivery).where(
                HyperlinkTaskDelivery.message_delivery_id == delivery.id
            )
        )
        if task_delivery is not None:
            task_delivery.submission_status = "accepted"
            task_delivery.submitted_at = task_delivery.submitted_at or delivery.queued_at
            task_delivery.status = delivery.status
            task_delivery.last_error = delivery.last_error
            task = db.get(HyperlinkTask, task_delivery.task_id)
            if task is not None:
                db.flush()
                from app.routers.hyperlink import _sync_task_counts

                _sync_task_counts(db, task)
        db.commit()
        return {
            "data": {
                "ok": True,
                "duplicate": duplicate,
                "messageDelivery": delivery_row(delivery),
            }
        }
