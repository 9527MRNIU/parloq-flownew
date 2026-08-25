from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

# A worker is an independent Snowflake writer.
os.environ.setdefault(
    "SNOWFLAKE_NODE_ID", os.getenv("WORKER_SNOWFLAKE_NODE_ID", "2")
)

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.entity_ids import identifier_filter
from app.hyperlink_messages import render_hyperlink_message
from app.hyperlink_strategy import HyperlinkStrategyPolicy, strategy_policy
from app.material_files import material_delivery_reference
from app.models import (
    DataPackageRecipient,
    HyperlinkStrategy,
    HyperlinkTask,
    HyperlinkTaskAccountSlot,
    HyperlinkTaskDelivery,
    HyperlinkTemplate,
    Material,
    MessageDelivery,
    PersonalAccount,
    ProtocolNode,
)
from app.security import utcnow
from app.services.account_group_wakeups import dispatch_pending_group_wakeups
from app.services.account_metadata_sync import (
    process_pending_account_metadata_sync_jobs,
)
from app.services.domain_onboarding_worker import process_domain_onboarding_once
from app.services.meta_conversions import process_due_meta_conversions
from app.services.protocol_builds import start_protocol_build_worker
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id, parse_snowflake_id
from app.task_queue import (
    QUEUE_KEY,
    QUEUE_ENQUEUED_AT_KEY,
    dispatch_due_hyperlink_tasks,
    enqueue_hyperlink_task,
    redis_client,
    schedule_hyperlink_task,
    task_queue_marker,
)
from app.worker_health import start_worker_heartbeat


logger = logging.getLogger("parloq.task-worker")
RECOVERY_INTERVAL_SECONDS = 30
SUBMITTING_STALE_SECONDS = 120
LOCK_TTL_SECONDS = 120
LOCK_RENEW_SECONDS = 30
NOT_SUBMITTED = "__parloq_not_submitted__"

# A task is intentionally processed in bounded database buffers. Keep account
# serialization and rate reservations outside an individual buffer so a fast
# requeue cannot reset the per-account QPS boundary between two batches.
_ACCOUNT_LIMITER_GUARD = threading.Lock()
_ACCOUNT_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}
_ACCOUNT_RATE_LOCKS: dict[int, threading.Lock] = {}
_ACCOUNT_NEXT_SLOTS: dict[int, float] = {}


@dataclass(slots=True)
class SendJob:
    task_id: int
    task_delivery_id: int
    message_delivery_id: int
    slot_id: int | None
    lease_token: str | None
    account_id: int
    gateway_account_id: str
    message_id: str
    recipient_e164: str
    message: dict[str, Any]


class AccountSendLimiter:
    """Serialize each account while allowing separate account slots in parallel."""

    def __init__(
        self,
        policy: HyperlinkStrategyPolicy,
        stop_event: threading.Event | None = None,
    ):
        self.policy = policy
        self.stop_event = stop_event

    def _resources(
        self, account_id: int
    ) -> tuple[threading.BoundedSemaphore, threading.Lock]:
        with _ACCOUNT_LIMITER_GUARD:
            semaphore = _ACCOUNT_SEMAPHORES.setdefault(
                account_id, threading.BoundedSemaphore(1)
            )
            rate_lock = _ACCOUNT_RATE_LOCKS.setdefault(account_id, threading.Lock())
        return semaphore, rate_lock

    def send(
        self, job: SendJob, gateway: WaGatewayClient
    ) -> tuple[SendJob, dict | None, str | None]:
        semaphore, rate_lock = self._resources(job.account_id)
        with semaphore:
            if self.stop_event is not None and self.stop_event.is_set():
                return job, None, NOT_SUBMITTED
            with rate_lock:
                now = time.monotonic()
                reserved = max(now, _ACCOUNT_NEXT_SLOTS.get(job.account_id, now))
                _ACCOUNT_NEXT_SLOTS[job.account_id] = reserved + (
                    1 / self.policy.max_qps
                )
            delay = max(reserved - time.monotonic(), 0.0)
            if self.policy.send_jitter_ms:
                delay += secrets.randbelow(self.policy.send_jitter_ms + 1) / 1000
            if delay and self.stop_event is not None:
                if self.stop_event.wait(delay):
                    return job, None, NOT_SUBMITTED
            elif delay:
                time.sleep(delay)
            if self.stop_event is not None and self.stop_event.is_set():
                return job, None, NOT_SUBMITTED
            if not _begin_submission(job):
                return job, None, NOT_SUBMITTED
            return _send(job, gateway)


def _send(
    job: SendJob, gateway: WaGatewayClient
) -> tuple[SendJob, dict | None, str | None]:
    try:
        result = gateway.send(
            job.gateway_account_id,
            job.message_id,
            job.recipient_e164,
            job.message,
        )
        return job, result, None
    except GatewayError as exc:
        return job, None, str(exc)


def _task_template(
    db, task: HyperlinkTask, live_template: HyperlinkTemplate
) -> tuple[dict[str, Any], Material | None]:
    snapshot = task.template_snapshot_json
    if isinstance(snapshot, dict) and isinstance(snapshot.get("contentJson"), dict):
        content = snapshot["contentJson"]
        material_snapshot = snapshot.get("material")
        material_id = (
            str(material_snapshot.get("id") or "")
            if isinstance(material_snapshot, dict)
            else ""
        )
        try:
            material = (
                db.get(Material, parse_snowflake_id(material_id))
                if material_id
                else None
            )
        except ValueError:
            material = None
        return content, material
    material = (
        db.get(Material, live_template.material_id)
        if live_template.material_id
        else None
    )
    return live_template.content_json or {}, material


def _dispatchable_account_filter(task: HyperlinkTask):
    now = utcnow()
    return (
        PersonalAccount.group_id == task.account_group_id,
        PersonalAccount.created_by == task.created_by,
        PersonalAccount.enabled.is_(True),
        PersonalAccount.marketing_eligible.is_(True),
        PersonalAccount.deleted_at.is_(None),
        PersonalAccount.admission_status == "active",
        PersonalAccount.validation_status == "ready",
        or_(
            PersonalAccount.status.in_(("online_idle", "sending")),
            and_(
                ProtocolNode.connection_policy == "on_demand",
                PersonalAccount.status == "linked_offline",
            ),
        ),
        or_(
            PersonalAccount.sending_cooldown_until.is_(None),
            PersonalAccount.sending_cooldown_until <= now,
        ),
        ProtocolNode.marketing_enabled.is_(True),
        ProtocolNode.online_enabled.is_(True),
    )


def _release_slot(
    db,
    slot: HyperlinkTaskAccountSlot,
    *,
    reason: str,
    error: str | None = None,
    final: bool = False,
) -> None:
    """Release a sticky account and return only unsubmitted leases to the pool."""

    for delivery in db.scalars(
        select(HyperlinkTaskDelivery).where(
            HyperlinkTaskDelivery.slot_id == slot.id,
            HyperlinkTaskDelivery.submission_status == "leased",
        )
    ).all():
        delivery.submission_status = "pending"
        delivery.status = "queued"
        delivery.account_id = None
        delivery.slot_id = None
        delivery.lease_token = None
        delivery.leased_at = None
        delivery.lease_expires_at = None
    slot.status = "released" if final else "vacant"
    slot.account_id = None
    slot.lease_token = None
    slot.lease_expires_at = None
    slot.released_at = utcnow()
    slot.switch_count = int(slot.switch_count or 0) + (0 if final else 1)
    slot.consecutive_failure_count = 0
    slot.last_switch_reason = reason[:64]
    slot.last_error = error[:2000] if error else None


def _ensure_active_slots(
    db,
    task: HyperlinkTask,
    policy: HyperlinkStrategyPolicy,
) -> list[HyperlinkTaskAccountSlot]:
    """Keep up to task-concurrency accounts exclusively attached to this task."""

    slots = list(
        db.scalars(
            select(HyperlinkTaskAccountSlot)
            .where(HyperlinkTaskAccountSlot.task_id == task.id)
            .order_by(HyperlinkTaskAccountSlot.slot_index)
            .with_for_update()
        ).all()
    )
    by_index = {slot.slot_index: slot for slot in slots}
    for slot_index in range(policy.concurrency):
        if slot_index not in by_index:
            slot = HyperlinkTaskAccountSlot(
                task_id=task.id, slot_index=slot_index, status="vacant"
            )
            db.add(slot)
            db.flush()
            slots.append(slot)
            by_index[slot_index] = slot

    desired = [by_index[index] for index in range(policy.concurrency)]
    for slot in slots:
        if slot.slot_index >= policy.concurrency and slot.account_id is not None:
            _release_slot(db, slot, reason="concurrency_reduced", final=True)

    dispatchable_ids = set(
        db.scalars(
            select(PersonalAccount.id)
            .join(ProtocolNode, ProtocolNode.id == PersonalAccount.protocol_id)
            .where(*_dispatchable_account_filter(task))
        ).all()
    )
    for slot in desired:
        if slot.account_id is not None and slot.account_id not in dispatchable_ids:
            _release_slot(db, slot, reason="account_unavailable")
        elif slot.account_id is not None:
            slot.status = "active"
            slot.lease_expires_at = utcnow() + timedelta(
                seconds=max(policy.delivery_lease_seconds * 4, 300)
            )

    occupied_ids = set(
        db.scalars(
            select(HyperlinkTaskAccountSlot.account_id).where(
                HyperlinkTaskAccountSlot.account_id.is_not(None)
            )
        ).all()
    )
    candidates = list(
        db.scalars(
            select(PersonalAccount)
            .join(ProtocolNode, ProtocolNode.id == PersonalAccount.protocol_id)
            .where(
                *_dispatchable_account_filter(task),
                PersonalAccount.id.not_in(occupied_ids) if occupied_ids else True,
            )
            .order_by(PersonalAccount.id)
            .with_for_update(skip_locked=True)
        ).all()
    )
    candidate_index = 0
    for slot in desired:
        if slot.account_id is not None:
            continue
        while candidate_index < len(candidates):
            account = candidates[candidate_index]
            candidate_index += 1
            try:
                with db.begin_nested():
                    slot.account_id = account.id
                    slot.status = "active"
                    slot.lease_token = secrets.token_urlsafe(24)
                    slot.lease_expires_at = utcnow() + timedelta(
                        seconds=max(policy.delivery_lease_seconds * 4, 300)
                    )
                    slot.acquired_at = utcnow()
                    slot.released_at = None
                    slot.consecutive_failure_count = 0
                    slot.last_switch_reason = None
                    slot.last_error = None
                    db.flush()
                occupied_ids.add(account.id)
                break
            except IntegrityError:
                # Another task acquired this account between selection and
                # flush. The savepoint keeps the rest of this batch intact.
                slot.account_id = None
                slot.status = "vacant"
                slot.lease_token = None
                slot.lease_expires_at = None

    active = [slot for slot in desired if slot.account_id is not None]
    if active:
        task.status = "running"
    else:
        task.status = (
            "waiting_accounts"
            if policy.no_account_action == "wait"
            else "paused"
        )
    return active


def _pending_submission_filter(retry_ready_before):
    return or_(
        HyperlinkTaskDelivery.submission_status == "pending",
        and_(
            HyperlinkTaskDelivery.submission_status == "retry",
            HyperlinkTaskDelivery.updated_at <= retry_ready_before,
        ),
        and_(
            HyperlinkTaskDelivery.submission_status == "leased",
            HyperlinkTaskDelivery.lease_expires_at <= utcnow(),
        ),
    )


def _legacy_records(db, task: HyperlinkTask, policy: HyperlinkStrategyPolicy):
    retry_ready_before = utcnow() - timedelta(
        seconds=policy.retry_backoff_seconds
    )
    return list(
        db.execute(
            select(
                HyperlinkTaskDelivery,
                DataPackageRecipient,
                PersonalAccount,
                MessageDelivery,
            )
            .join(
                DataPackageRecipient,
                DataPackageRecipient.id == HyperlinkTaskDelivery.recipient_id,
            )
            .join(
                PersonalAccount,
                PersonalAccount.id == HyperlinkTaskDelivery.account_id,
            )
            .join(ProtocolNode, ProtocolNode.id == PersonalAccount.protocol_id)
            .outerjoin(
                MessageDelivery,
                MessageDelivery.id == HyperlinkTaskDelivery.message_delivery_id,
            )
            .where(
                HyperlinkTaskDelivery.task_id == task.id,
                _pending_submission_filter(retry_ready_before),
                PersonalAccount.enabled.is_(True),
                PersonalAccount.marketing_eligible.is_(True),
                PersonalAccount.deleted_at.is_(None),
                PersonalAccount.admission_status == "active",
                PersonalAccount.status.in_(("online_idle", "sending")),
                ProtocolNode.marketing_enabled.is_(True),
                ProtocolNode.online_enabled.is_(True),
            )
            .order_by(HyperlinkTaskDelivery.id)
            .limit(policy.buffer_size)
            .with_for_update(skip_locked=True)
        ).all()
    )


def _prepare_batch(
    task_id: str,
) -> tuple[list[SendJob], HyperlinkStrategyPolicy] | None:
    """Atomically lease a short recipient buffer to long-lived account slots."""

    with SessionLocal() as db:
        task = db.scalar(
            select(HyperlinkTask)
            .where(identifier_filter(HyperlinkTask, task_id))
            .with_for_update()
        )
        if (
            task is None
            or task.status not in {"running", "waiting_accounts"}
        ):
            return None
        strategy = db.get(HyperlinkStrategy, task.strategy_id)
        template = db.get(HyperlinkTemplate, task.template_id)
        if strategy is None or template is None:
            task.status = "failed"
            db.commit()
            return None
        if not strategy.enabled:
            task.status = "paused"
            task.paused_at = utcnow()
            db.commit()
            return None

        policy = strategy_policy(strategy)
        content, material = _task_template(db, task, template)
        retry_ready_before = utcnow() - timedelta(
            seconds=policy.retry_backoff_seconds
        )

        dynamic_rows: list[
            tuple[
                HyperlinkTaskDelivery,
                DataPackageRecipient,
                PersonalAccount,
                MessageDelivery | None,
                HyperlinkTaskAccountSlot | None,
            ]
        ] = []
        if task.sender_mode == "dynamic_group":
            slots = _ensure_active_slots(db, task, policy)
            if not slots:
                db.commit()
                return [], policy
            pending = list(
                db.execute(
                    select(
                        HyperlinkTaskDelivery,
                        DataPackageRecipient,
                        MessageDelivery,
                    )
                    .join(
                        DataPackageRecipient,
                        DataPackageRecipient.id
                        == HyperlinkTaskDelivery.recipient_id,
                    )
                    .outerjoin(
                        MessageDelivery,
                        MessageDelivery.id
                        == HyperlinkTaskDelivery.message_delivery_id,
                    )
                    .where(
                        HyperlinkTaskDelivery.task_id == task.id,
                        DataPackageRecipient.validation_status == "valid",
                        _pending_submission_filter(retry_ready_before),
                    )
                    .order_by(HyperlinkTaskDelivery.id)
                    .limit(policy.buffer_size)
                    .with_for_update(skip_locked=True)
                ).all()
            )
            accounts = {
                account.id: account
                for account in db.scalars(
                    select(PersonalAccount).where(
                        PersonalAccount.id.in_(
                            [slot.account_id for slot in slots if slot.account_id]
                        )
                    )
                ).all()
            }
            leased_at = utcnow()
            lease_expires_at = leased_at + timedelta(
                seconds=policy.delivery_lease_seconds
            )
            for index, (delivery, recipient, message) in enumerate(pending):
                slot = slots[index % len(slots)]
                account = accounts[slot.account_id]
                lease_token = secrets.token_urlsafe(24)
                delivery.account_id = account.id
                delivery.slot_id = slot.id
                delivery.lease_token = lease_token
                delivery.leased_at = leased_at
                delivery.lease_expires_at = lease_expires_at
                delivery.submission_status = "leased"
                delivery.status = "queued"
                delivery.last_error = None
                if message is not None:
                    message.account_id = account.id
                dynamic_rows.append((delivery, recipient, account, message, slot))
            rows = dynamic_rows
        else:
            rows = [
                (delivery, recipient, account, message, None)
                for delivery, recipient, account, message in _legacy_records(
                    db, task, policy
                )
            ]

        if not rows:
            pending_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(HyperlinkTaskDelivery)
                    .where(
                        HyperlinkTaskDelivery.task_id == task.id,
                        HyperlinkTaskDelivery.submission_status.in_(
                            ("pending", "retry", "leased")
                        ),
                    )
                )
                or 0
            )
            if pending_count and task.sender_mode == "legacy_fixed":
                task.status = "paused"
                task.paused_at = utcnow()
            db.commit()
            return [], policy

        message_ids = {
            delivery.id: f"{task.id}:{recipient.id}"
            for delivery, recipient, _account, _message, _slot in rows
        }
        existing_messages = {
            message.request_id: message
            for message in db.scalars(
                select(MessageDelivery).where(
                    MessageDelivery.request_id.in_(message_ids.values())
                )
            ).all()
        }
        header = content.get("header") if isinstance(content, dict) else None
        header_type = (
            str(header.get("type") or "none")
            if isinstance(header, dict)
            else "none"
        )
        material_reference = (
            material_delivery_reference(material)
            if material is not None
            and header_type in {"image", "video", "document"}
            else None
        )
        jobs: list[SendJob] = []
        for delivery, recipient, account, joined_message, slot in rows:
            message_id = message_ids[delivery.id]
            message = joined_message or existing_messages.get(message_id)
            if message is not None and message.status in {"sent", "delivered"}:
                delivery.submission_status = "accepted"
                delivery.submitted_at = delivery.submitted_at or utcnow()
                delivery.status = message.status
                delivery.lease_token = None
                delivery.lease_expires_at = None
                continue
            if message is None:
                message = MessageDelivery(
                    public_id=new_public_id("msg"),
                    request_id=message_id,
                    account_id=account.id,
                    recipient_e164=recipient.phone_e164,
                    status="queued",
                    queued_at=utcnow(),
                )
                db.add(message)
                db.flush()
            else:
                message.account_id = account.id
                message.status = "queued"
                message.failed_at = None
                message.last_error = None
            delivery.message_delivery_id = message.id
            if task.sender_mode == "legacy_fixed":
                delivery.submission_status = "leased"
                delivery.lease_token = secrets.token_urlsafe(24)
                delivery.leased_at = utcnow()
                delivery.lease_expires_at = utcnow() + timedelta(
                    seconds=policy.delivery_lease_seconds
                )
            jobs.append(
                SendJob(
                    task_id=task.id,
                    task_delivery_id=delivery.id,
                    message_delivery_id=message.id,
                    slot_id=slot.id if slot else None,
                    lease_token=delivery.lease_token,
                    account_id=account.id,
                    gateway_account_id=account.gateway_account_id,
                    message_id=message.public_id,
                    recipient_e164=recipient.phone_e164,
                    message=render_hyperlink_message(
                        content,
                        recipient.variables_json,
                        material_type=(material.material_type if material else None),
                        material_reference=material_reference,
                    ),
                )
            )
        db.commit()
        return jobs, policy


def _begin_submission(job: SendJob) -> bool:
    """Cross the irreversible boundary only while the task and lease are valid."""

    with SessionLocal() as db:
        delivery = db.scalar(
            select(HyperlinkTaskDelivery)
            .where(HyperlinkTaskDelivery.id == job.task_delivery_id)
            .with_for_update()
        )
        task = db.get(HyperlinkTask, job.task_id)
        if (
            delivery is None
            or task is None
            or task.status != "running"
            or delivery.submission_status != "leased"
            or delivery.lease_token != job.lease_token
            or delivery.account_id != job.account_id
        ):
            return False
        delivery.submission_status = "submitting"
        delivery.attempt_count = int(delivery.attempt_count or 0) + 1
        delivery.lease_expires_at = utcnow() + timedelta(
            seconds=SUBMITTING_STALE_SECONDS
        )
        message = db.get(MessageDelivery, job.message_delivery_id)
        if message is not None:
            message.status = "queued"
            message.queued_at = message.queued_at or utcnow()
        db.commit()
        return True


def _persist_results(
    results: list[tuple[SendJob, dict | None, str | None]],
    policy: HyperlinkStrategyPolicy,
) -> None:
    retry_task_ids: set[int] = set()
    cooldown_task_ids: set[int] = set()
    with SessionLocal() as db:
        task_ids: set[int] = set()
        for job, response, error in results:
            delivery = db.get(HyperlinkTaskDelivery, job.task_delivery_id)
            message = db.get(MessageDelivery, job.message_delivery_id)
            if delivery is None or message is None:
                continue
            task_ids.add(delivery.task_id)
            slot = (
                db.get(HyperlinkTaskAccountSlot, job.slot_id)
                if job.slot_id is not None
                else None
            )
            if error == NOT_SUBMITTED:
                if (
                    delivery.submission_status == "leased"
                    and delivery.lease_token == job.lease_token
                ):
                    delivery.submission_status = "pending"
                    delivery.account_id = None if slot is not None else delivery.account_id
                    delivery.slot_id = None
                    delivery.lease_token = None
                    delivery.leased_at = None
                    delivery.lease_expires_at = None
                continue
            response_status = str((response or {}).get("status") or "").lower()
            if not error and response_status == "failed":
                error = str(
                    (response or {}).get("error")
                    or (response or {}).get("message")
                    or "网关拒绝提交消息"
                )
            if error:
                safe_error = error[:2000]
                message.last_error = safe_error
                delivery.last_error = safe_error
                delivery.lease_token = None
                delivery.lease_expires_at = None
                if delivery.attempt_count <= policy.retry_limit:
                    delivery.submission_status = "retry"
                    delivery.status = "queued"
                    retry_task_ids.add(delivery.task_id)
                else:
                    delivery.submission_status = "failed"
                    delivery.submission_failed_at = utcnow()
                    delivery.status = "failed"
                    message.status = "failed"
                    message.failed_at = utcnow()

                if slot is not None and slot.account_id == job.account_id:
                    slot.consecutive_failure_count = int(
                        slot.consecutive_failure_count or 0
                    ) + 1
                    slot.last_error = safe_error
                    account = db.get(PersonalAccount, job.account_id)
                    account_invalid = account is None or account.status not in {
                        "online_idle",
                        "sending",
                    }
                    if account_invalid or (
                        slot.consecutive_failure_count
                        >= policy.account_failure_threshold
                    ):
                        if account is not None and policy.account_cooldown_seconds:
                            account.sending_cooldown_until = utcnow() + timedelta(
                                seconds=policy.account_cooldown_seconds
                            )
                        _release_slot(
                            db,
                            slot,
                            reason=(
                                "account_state_changed"
                                if account_invalid
                                else "failure_threshold"
                            ),
                            error=safe_error,
                        )
                        cooldown_task_ids.add(delivery.task_id)
                    if delivery.submission_status == "retry":
                        # The account remains attached to the sticky slot when
                        # it is healthy, but this recipient is returned to the
                        # task pool so a replacement slot can also claim it.
                        delivery.slot_id = None
                        delivery.account_id = None
                    else:
                        delivery.slot_id = None
                continue

            message.provider_message_id = (
                str((response or {}).get("providerMessageId") or "")[:255]
                or None
            )
            next_status = str((response or {}).get("status") or "queued")
            if next_status not in {"queued", "sent", "delivered", "failed"}:
                next_status = "queued"
            ranks = {"queued": 0, "sent": 1, "delivered": 2}
            if message.status != "failed" and ranks.get(next_status, 0) >= ranks.get(
                message.status, 0
            ):
                message.status = next_status
            delivery.submission_status = "accepted"
            delivery.submitted_at = delivery.submitted_at or utcnow()
            delivery.submission_failed_at = None
            delivery.status = message.status
            delivery.lease_token = None
            delivery.lease_expires_at = None
            if slot is not None and slot.account_id == job.account_id:
                slot.consecutive_failure_count = 0
                slot.last_error = None

        if task_ids:
            from app.routers.hyperlink import _sync_task_counts

            for task_id in task_ids:
                task = db.get(HyperlinkTask, task_id)
                if task is not None:
                    _sync_task_counts(db, task)
        db.commit()

    for task_id in retry_task_ids:
        try:
            schedule_hyperlink_task(str(task_id), policy.retry_backoff_seconds)
        except Exception:
            logger.exception(
                "hyperlink_task_retry_schedule_failed",
                extra={"task_id": str(task_id)},
            )
    for task_id in cooldown_task_ids:
        try:
            schedule_hyperlink_task(
                str(task_id), max(policy.account_cooldown_seconds, 1)
            )
        except Exception:
            logger.exception(
                "hyperlink_task_account_replacement_schedule_failed",
                extra={"task_id": str(task_id)},
            )


def _has_ready_work(task_id: str, policy: HyperlinkStrategyPolicy) -> bool:
    retry_ready_before = utcnow() - timedelta(
        seconds=policy.retry_backoff_seconds
    )
    with SessionLocal() as db:
        task = db.scalar(
            select(HyperlinkTask).where(identifier_filter(HyperlinkTask, task_id))
        )
        if task is None or task.status != "running":
            return False
        return bool(
            db.scalar(
                select(func.count())
                .select_from(HyperlinkTaskDelivery)
                .where(
                    HyperlinkTaskDelivery.task_id == task.id,
                    _pending_submission_filter(retry_ready_before),
                )
            )
        )


def _send_account_jobs(
    jobs: list[SendJob],
    limiter: AccountSendLimiter,
    gateway: WaGatewayClient,
) -> list[tuple[SendJob, dict | None, str | None]]:
    return [limiter.send(job, gateway) for job in jobs]


def process_task(
    task_id: str,
    gateway: WaGatewayClient | None = None,
    stop_event: threading.Event | None = None,
) -> bool:
    """Process bounded buffers with sticky account slots.

    Production handles one buffer per queue turn for fairness. Tests without a
    real queue drain all buffers synchronously.
    """

    gateway = gateway or WaGatewayClient()
    drain_synchronously = get_settings().task_queue_mock
    should_requeue = False
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        prepared = _prepare_batch(task_id)
        if prepared is None:
            return False
        jobs, policy = prepared
        if not jobs:
            return False
        limiter = AccountSendLimiter(policy, stop_event=stop_event)
        grouped: dict[int, list[SendJob]] = defaultdict(list)
        for job in jobs:
            grouped[job.account_id].append(job)
        max_workers = min(
            len(grouped),
            policy.concurrency,
            get_settings().task_worker_max_concurrency,
        )
        results: list[tuple[SendJob, dict | None, str | None]] = []
        with ThreadPoolExecutor(max_workers=max(max_workers, 1)) as executor:
            futures = [
                executor.submit(_send_account_jobs, rows, limiter, gateway)
                for rows in grouped.values()
            ]
            for future in as_completed(futures):
                results.extend(future.result())
        _persist_results(results, policy)
        should_requeue = _has_ready_work(task_id, policy)
        if not drain_synchronously or not should_requeue:
            return should_requeue


def recover_running_tasks() -> int:
    """Recover safe leases and wake unresolved tasks as a fallback safety net."""

    with SessionLocal() as db:
        now = utcnow()
        stale_before = now - timedelta(seconds=SUBMITTING_STALE_SECONDS)
        expired_leases = db.scalars(
            select(HyperlinkTaskDelivery)
            .join(HyperlinkTask, HyperlinkTask.id == HyperlinkTaskDelivery.task_id)
            .where(
                HyperlinkTask.status.in_(("running", "waiting_accounts")),
                HyperlinkTaskDelivery.submission_status == "leased",
                HyperlinkTaskDelivery.lease_expires_at <= now,
            )
        ).all()
        for delivery in expired_leases:
            delivery.submission_status = "pending"
            delivery.account_id = None
            delivery.slot_id = None
            delivery.lease_token = None
            delivery.leased_at = None
            delivery.lease_expires_at = None
            delivery.last_error = "发送租约已自动回收"

        stuck = db.scalars(
            select(HyperlinkTaskDelivery)
            .join(HyperlinkTask, HyperlinkTask.id == HyperlinkTaskDelivery.task_id)
            .where(
                HyperlinkTask.status.in_(("running", "waiting_accounts")),
                HyperlinkTaskDelivery.submission_status == "submitting",
                HyperlinkTaskDelivery.updated_at <= stale_before,
            )
        ).all()
        for delivery in stuck:
            # Sending may already have crossed the gateway boundary. Retrying
            # blindly can duplicate a message, so reconciliation is explicit.
            delivery.submission_status = "reconciling"
            delivery.last_error = "网关提交结果待核对"

        unresolved = (
            select(func.count())
            .select_from(HyperlinkTaskDelivery)
            .where(
                HyperlinkTaskDelivery.task_id == HyperlinkTask.id,
                HyperlinkTaskDelivery.submission_status.in_(
                    ("pending", "retry", "leased")
                ),
            )
            .correlate(HyperlinkTask)
            .scalar_subquery()
        )
        task_ids = list(
            db.scalars(
                select(HyperlinkTask.id).where(
                    HyperlinkTask.status.in_(("running", "waiting_accounts")),
                    unresolved > 0,
                )
            ).all()
        )
        db.commit()
    queued = 0
    for task_id in task_ids:
        queued += int(enqueue_hyperlink_task(str(task_id)))
    return queued


LOCK_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _renew_lock(
    client,
    lock_key: str,
    token: str,
    stopped: threading.Event,
    lock_lost: threading.Event,
) -> None:
    while not stopped.wait(LOCK_RENEW_SECONDS):
        try:
            if not client.eval(
                LOCK_RENEW_SCRIPT, 1, lock_key, token, LOCK_TTL_SECONDS
            ):
                lock_lost.set()
                return
        except Exception:
            logger.exception("hyperlink_task_lock_renewal_failed")
            lock_lost.set()
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = redis_client()
    start_worker_heartbeat(client)
    start_protocol_build_worker()
    gateway = WaGatewayClient()
    last_recovery = 0.0
    while True:
        try:
            with SessionLocal() as db:
                processed_domains = process_domain_onboarding_once(db, limit=2)
            if processed_domains:
                logger.info(
                    "domain_onboarding_batch_processed",
                    extra={"processed": processed_domains},
                )
        except Exception:
            logger.exception("domain_onboarding_batch_failed")
        try:
            result = process_due_meta_conversions()
            if result["claimed"]:
                logger.info("meta_capi_batch_processed", extra=result)
        except Exception:
            logger.exception("meta_capi_delivery_failed")
        try:
            dispatch_due_hyperlink_tasks()
        except Exception:
            logger.exception("hyperlink_delayed_task_dispatch_failed")
        try:
            dispatch_pending_group_wakeups()
        except Exception:
            logger.exception("account_group_wakeup_dispatch_failed")
        try:
            if client.llen(QUEUE_KEY) == 0:
                metadata_result = process_pending_account_metadata_sync_jobs(limit=1)
                if metadata_result["claimed"]:
                    logger.info(
                        "account_metadata_sync_processed", extra=metadata_result
                    )
        except Exception:
            logger.exception("account_metadata_sync_failed")
        if time.monotonic() - last_recovery >= RECOVERY_INTERVAL_SECONDS:
            try:
                recover_running_tasks()
            except Exception:
                logger.exception("hyperlink_task_recovery_failed")
            last_recovery = time.monotonic()
        item = client.blpop(QUEUE_KEY, timeout=5)
        if not item:
            continue
        _, task_id = item
        client.zrem(QUEUE_ENQUEUED_AT_KEY, task_id)
        client.delete(task_queue_marker(task_id))
        lock_key = f"parloq:hyperlink:task-lock:{task_id}"
        token = secrets.token_urlsafe(24)
        if not client.set(lock_key, token, ex=LOCK_TTL_SECONDS, nx=True):
            continue
        stopped = threading.Event()
        lock_lost = threading.Event()
        heartbeat = threading.Thread(
            target=_renew_lock,
            args=(client, lock_key, token, stopped, lock_lost),
            daemon=True,
        )
        heartbeat.start()
        requeue = False
        try:
            requeue = process_task(task_id, gateway, stop_event=lock_lost)
        except Exception:
            logger.exception("hyperlink_task_failed", extra={"task_id": task_id})
        finally:
            stopped.set()
            heartbeat.join(timeout=2)
            client.eval(LOCK_RELEASE_SCRIPT, 1, lock_key, token)
        if requeue and not lock_lost.is_set():
            enqueue_hyperlink_task(task_id)


if __name__ == "__main__":
    main()
