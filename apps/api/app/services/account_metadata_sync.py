from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AccountMetadataSyncJob, PersonalAccount, ProtocolNode
from app.security import utcnow
from app.services.account_avatars import apply_gateway_avatar
from app.services.protocol_nodes import normalized_sync_policy
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id


ACTIVE_JOB_STATUSES = {"pending", "running"}


def metadata_sync_job_row(item: AccountMetadataSyncJob) -> dict:
    return {
        "id": str(item.id),
        "accountId": str(item.account_id),
        "protocolId": str(item.protocol_node_id),
        "syncPolicyVersion": item.sync_policy_version,
        "syncPolicy": item.sync_policy_json,
        "status": item.status,
        "attemptCount": item.attempt_count,
        "startedAt": item.started_at.isoformat() if item.started_at else None,
        "completedAt": item.completed_at.isoformat() if item.completed_at else None,
        "lastError": item.last_error,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


def enqueue_account_metadata_sync(
    db: Session,
    account: PersonalAccount,
    *,
    sync_policy: dict | None = None,
    sync_policy_version: int | None = None,
) -> AccountMetadataSyncJob:
    """Create one durable metadata job, deduplicated per active account run."""

    active_key = f"account:{account.id}"
    existing = db.scalar(
        select(AccountMetadataSyncJob).where(
            AccountMetadataSyncJob.active_key == active_key,
            AccountMetadataSyncJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    protocol = db.get(ProtocolNode, account.protocol_id)
    policy = normalized_sync_policy(
        sync_policy
        if isinstance(sync_policy, dict)
        else protocol.sync_policy_json if protocol is not None else None
    )
    version = (
        sync_policy_version
        if sync_policy_version is not None
        else protocol.sync_policy_version if protocol is not None else 1
    )
    item = AccountMetadataSyncJob(
        public_id=new_public_id("amsync"),
        account_id=account.id,
        protocol_node_id=account.protocol_id,
        sync_policy_version=version,
        sync_policy_json=policy,
        status="pending",
        active_key=active_key,
        attempt_count=0,
        result_json={},
        created_by=account.created_by,
    )
    account.metadata_sync_status = "pending"
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(AccountMetadataSyncJob).where(
                AccountMetadataSyncJob.active_key == active_key,
                AccountMetadataSyncJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        if existing is None:
            raise
        return existing
    return item


def _apply_gateway_metadata(account: PersonalAccount, value: dict) -> None:
    metadata_status = value.get("metadataSyncStatus")
    if metadata_status in {"ready", "unsupported"}:
        account.metadata_sync_status = metadata_status
    else:
        account.metadata_sync_status = "ready"
    quality = value.get("quality")
    quality_known = False
    if isinstance(quality, dict):
        if isinstance(quality.get("hasAvatar"), bool):
            account.has_avatar = quality["hasAvatar"]
            quality_known = True
        for source_key, attribute in (
            ("groupCount", "group_count"),
            ("friendCount", "friend_count"),
            ("mutualContactCount", "mutual_contact_count"),
        ):
            metric = quality.get(source_key)
            if isinstance(metric, int) and not isinstance(metric, bool) and metric >= 0:
                setattr(account, attribute, metric)
                quality_known = True
    if quality_known:
        account.quality_synced_at = utcnow()
    apply_gateway_avatar(account, value)
    account.last_error = None


def _claim_jobs(limit: int) -> list[int]:
    with SessionLocal() as db:
        stale_before = utcnow() - timedelta(minutes=5)
        jobs = list(
            db.scalars(
                select(AccountMetadataSyncJob)
                .where(
                    (AccountMetadataSyncJob.status == "pending")
                    | (
                        (AccountMetadataSyncJob.status == "running")
                        & (AccountMetadataSyncJob.started_at < stale_before)
                    )
                )
                .order_by(
                    AccountMetadataSyncJob.created_at,
                    AccountMetadataSyncJob.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        now = utcnow()
        for job in jobs:
            job.status = "running"
            job.started_at = now
            job.completed_at = None
            job.last_error = None
            job.attempt_count = int(job.attempt_count or 0) + 1
            account = db.get(PersonalAccount, job.account_id)
            if account is not None:
                account.metadata_sync_status = "syncing"
        db.commit()
        return [job.id for job in jobs]


def process_pending_account_metadata_sync_jobs(limit: int = 1) -> dict[str, int]:
    """Run pending jobs once; gateway owns only its short in-request retries."""

    job_ids = _claim_jobs(max(1, min(limit, 20)))
    succeeded = 0
    failed = 0
    for job_id in job_ids:
        with SessionLocal() as db:
            job = db.get(AccountMetadataSyncJob, job_id)
            account = db.get(PersonalAccount, job.account_id) if job else None
            if job is None:
                continue
            try:
                if account is None:
                    raise GatewayError("账号已不存在")
                if account.admission_status != "active":
                    raise GatewayError("账号尚未正式入池")
                value = WaGatewayClient().sync_metadata(
                    account.gateway_account_id,
                    job.sync_policy_json,
                )
                _apply_gateway_metadata(account, value)
                job.status = "succeeded"
                job.result_json = {
                    "metadataSyncStatus": account.metadata_sync_status,
                    "quality": value.get("quality") if isinstance(value, dict) else {},
                }
                succeeded += 1
            except GatewayError as exc:
                job.status = "failed"
                job.last_error = str(exc)[:2000]
                if account is not None:
                    account.metadata_sync_status = "failed"
                    account.last_error = str(exc)[:2000]
                failed += 1
            job.completed_at = utcnow()
            job.active_key = None
            db.commit()
    return {"claimed": len(job_ids), "succeeded": succeeded, "failed": failed}
