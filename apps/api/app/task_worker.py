from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, or_, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    DataPackageRecipient,
    HyperlinkStrategy,
    HyperlinkTask,
    HyperlinkTaskDelivery,
    HyperlinkTemplate,
    MessageDelivery,
    PersonalAccount,
    ProtocolNode,
)
from app.security import utcnow
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.task_queue import QUEUE_KEY, redis_client


logger = logging.getLogger("parloq.task-worker")


@dataclass(slots=True)
class SendJob:
    task_delivery_id: int
    message_delivery_id: int
    account_public_id: str
    message_id: str
    recipient_e164: str
    text: str


def _render_text(content: dict, variables: dict) -> str:
    template = str(content.get("text") or content.get("message") or "")
    return re.sub(
        r"\{\{\s*([A-Za-z0-9_]{1,64})\s*\}\}",
        lambda match: str(variables.get(match.group(1), ""))[:500],
        template,
    )[:4096]


def _send(
    job: SendJob, gateway: WaGatewayClient
) -> tuple[SendJob, dict | None, str | None]:
    try:
        result = gateway.send(
            job.account_public_id,
            job.message_id,
            job.recipient_e164,
            job.text,
        )
        return job, result, None
    except GatewayError as exc:
        return job, None, str(exc)


def _prepare_batch(task_public_id: str) -> tuple[list[SendJob], int, int] | None:
    with SessionLocal() as db:
        task = db.scalar(
            select(HyperlinkTask).where(HyperlinkTask.public_id == task_public_id)
        )
        if task is None or task.archived_at is not None or task.status != "running":
            return None
        strategy = db.get(HyperlinkStrategy, task.strategy_id)
        template = db.get(HyperlinkTemplate, task.template_id)
        if strategy is None or template is None:
            task.status = "failed"
            db.commit()
            return None
        records = db.execute(
            select(
                HyperlinkTaskDelivery,
                DataPackageRecipient,
                PersonalAccount,
            )
            .join(
                DataPackageRecipient,
                DataPackageRecipient.id == HyperlinkTaskDelivery.recipient_id,
            )
            .join(PersonalAccount, PersonalAccount.id == HyperlinkTaskDelivery.account_id)
            .join(ProtocolNode, ProtocolNode.id == PersonalAccount.protocol_id)
            .where(
                HyperlinkTaskDelivery.task_id == task.id,
                HyperlinkTaskDelivery.status.in_(("queued", "retry")),
                or_(
                    HyperlinkTaskDelivery.message_delivery_id.is_(None),
                    HyperlinkTaskDelivery.status == "retry",
                ),
                PersonalAccount.enabled.is_(True),
                PersonalAccount.status.in_(("online_idle", "sending")),
                ProtocolNode.marketing_enabled.is_(True),
                ProtocolNode.online_enabled.is_(True),
                ProtocolNode.archived_at.is_(None),
            )
            .order_by(HyperlinkTaskDelivery.id)
            .limit(strategy.batch_size)
        ).all()
        if not records:
            pending_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(HyperlinkTaskDelivery)
                    .where(
                        HyperlinkTaskDelivery.task_id == task.id,
                        HyperlinkTaskDelivery.status.in_(("queued", "retry")),
                        or_(
                            HyperlinkTaskDelivery.message_delivery_id.is_(None),
                            HyperlinkTaskDelivery.status == "retry",
                        ),
                    )
                )
                or 0
            )
            if pending_count:
                # The account's protocol may have been disabled after task
                # creation. Pause durably instead of leaving a running task
                # whose queued deliveries can never be selected.
                task.status = "paused"
                db.commit()
        message_ids = {
            delivery.id: f"{task.public_id}:{recipient.public_id}"
            for delivery, recipient, _account in records
        }
        existing_messages = {
            message.request_id: message
            for message in db.scalars(
                select(MessageDelivery).where(
                    MessageDelivery.request_id.in_(message_ids.values())
                )
            ).all()
        } if message_ids else {}
        jobs: list[SendJob] = []
        for delivery, recipient, account in records:
            message_id = message_ids[delivery.id]
            message = existing_messages.get(message_id)
            if message is None:
                message = MessageDelivery(
                    public_id=f"msg_{uuid4().hex}",
                    request_id=message_id,
                    account_id=account.id,
                    recipient_e164=recipient.phone_e164,
                    status="queued",
                    queued_at=utcnow(),
                )
                db.add(message)
                db.flush()
            else:
                message.status = "queued"
                message.failed_at = None
                message.last_error = None
            delivery.message_delivery_id = message.id
            delivery.attempt_count += 1
            delivery.status = "sending"
            delivery.last_error = None
            jobs.append(
                SendJob(
                    task_delivery_id=delivery.id,
                    message_delivery_id=message.id,
                    account_public_id=account.public_id,
                    message_id=message_id,
                    recipient_e164=recipient.phone_e164,
                    text=_render_text(template.content_json, recipient.variables_json),
                )
            )
        db.commit()
        concurrency = min(
            strategy.concurrency,
            get_settings().task_worker_max_concurrency,
            max(len(jobs), 1),
        )
        return jobs, concurrency, strategy.retry_limit


def _persist_results(
    results: list[tuple[SendJob, dict | None, str | None]], retry_limit: int
) -> None:
    with SessionLocal() as db:
        for job, response, error in results:
            delivery = db.get(HyperlinkTaskDelivery, job.task_delivery_id)
            message = db.get(MessageDelivery, job.message_delivery_id)
            if delivery is None or message is None:
                continue
            if error:
                message.last_error = error[:2000]
                delivery.last_error = error[:2000]
                if delivery.attempt_count <= retry_limit:
                    delivery.status = "retry"
                else:
                    delivery.status = "failed"
                    message.status = "failed"
                    message.failed_at = utcnow()
                continue
            message.provider_message_id = (
                str((response or {}).get("providerMessageId") or "")[:255] or None
            )
            message.status = "queued"
            delivery.status = "queued"
        db.commit()


def process_task(
    task_public_id: str, gateway: WaGatewayClient | None = None
) -> None:
    """Submit unsent task deliveries in bounded batches.

    The HTTP process creates the durable rows; this worker renders text only in
    memory and submits idempotent message IDs to the Baileys gateway.  It checks the
    task state between every batch, so pause/cancel take effect without waiting
    for the whole recipient set.
    """
    gateway = gateway or WaGatewayClient()
    while True:
        prepared = _prepare_batch(task_public_id)
        if prepared is None:
            return
        jobs, concurrency, retry_limit = prepared
        if not jobs:
            return
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(_send, job, gateway) for job in jobs]
            for future in as_completed(futures):
                results.append(future.result())
        _persist_results(results, retry_limit)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = redis_client()
    gateway = WaGatewayClient()
    while True:
        item = client.blpop(QUEUE_KEY, timeout=30)
        if not item:
            continue
        _, task_public_id = item
        lock_key = f"parloq:hyperlink:task-lock:{task_public_id}"
        if not client.set(lock_key, "1", ex=3600, nx=True):
            continue
        try:
            process_task(task_public_id, gateway)
        except Exception:
            logger.exception("hyperlink_task_failed", extra={"task_id": task_public_id})
        finally:
            client.delete(lock_key)


if __name__ == "__main__":
    main()
