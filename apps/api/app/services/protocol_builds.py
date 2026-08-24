from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import ProtocolBuildJob, ProtocolDefinition
from app.security import utcnow
from app.snowflake import new_public_id


logger = logging.getLogger("parloq.protocol-build-worker")
BUILD_LOG_LIMIT = 8_000
STALE_BUILD_AFTER = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class ProtocolBuildResult:
    artifact_digest: str
    artifact_integrity: str
    log_excerpt: str


class ProtocolBuilderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        log_excerpt: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.log_excerpt = log_excerpt


class ProtocolBuilder(Protocol):
    def build(
        self,
        *,
        definition_id: str,
        adapter_key: str,
        package_name: str,
        version: str,
        contract_version: int,
    ) -> ProtocolBuildResult: ...


class ProtocolBuilderClient:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self.base_url = settings.protocol_builder_url
        self.api_token = settings.protocol_builder_api_token
        self.timeout_seconds = settings.protocol_build_timeout_seconds
        self.http_client = http_client or httpx.Client()

    def build(
        self,
        *,
        definition_id: str,
        adapter_key: str,
        package_name: str,
        version: str,
        contract_version: int,
    ) -> ProtocolBuildResult:
        headers = (
            {"Authorization": f"Bearer {self.api_token}"}
            if self.api_token
            else {}
        )
        try:
            response = self.http_client.post(
                f"{self.base_url}/v1/protocol-builds",
                json={
                    "definitionId": definition_id,
                    "adapterKey": adapter_key,
                    "packageName": package_name,
                    "version": version,
                    "contractVersion": contract_version,
                },
                headers=headers,
                timeout=httpx.Timeout(self.timeout_seconds, connect=5.0),
            )
        except httpx.HTTPError as exc:
            raise ProtocolBuilderError(
                "builder_unavailable",
                "协议构建服务暂时不可用",
            ) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.is_success:
            error = payload.get("error") if isinstance(payload, dict) else None
            error = error if isinstance(error, dict) else {}
            raise ProtocolBuilderError(
                str(error.get("code") or "build_failed")[:64],
                str(error.get("message") or f"协议构建失败（{response.status_code}）")[:1024],
                log_excerpt=str(error.get("logExcerpt") or "")[:BUILD_LOG_LIMIT],
            )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ProtocolBuilderError("invalid_response", "协议构建服务返回无法识别的数据")
        digest = str(data.get("artifactDigest") or "")
        integrity = str(data.get("artifactIntegrity") or "")
        if len(digest) != 64 or not integrity:
            raise ProtocolBuilderError("invalid_response", "协议构建产物信息不完整")
        return ProtocolBuildResult(
            artifact_digest=digest,
            artifact_integrity=integrity[:255],
            log_excerpt=str(data.get("logExcerpt") or "")[:BUILD_LOG_LIMIT],
        )


def queue_protocol_build(
    db: Session,
    definition: ProtocolDefinition,
) -> ProtocolBuildJob:
    locked = db.scalar(
        select(ProtocolDefinition)
        .where(ProtocolDefinition.id == definition.id)
        .with_for_update()
    )
    if locked is None:
        raise ValueError("protocol definition no longer exists")
    active = db.scalar(
        select(ProtocolBuildJob.id).where(
            ProtocolBuildJob.protocol_definition_id == locked.id,
            ProtocolBuildJob.status.in_(("queued", "building")),
        )
    )
    if active is not None:
        raise ValueError("protocol definition already has an active build")
    attempt = int(
        db.scalar(
            select(func.max(ProtocolBuildJob.attempt_number)).where(
                ProtocolBuildJob.protocol_definition_id == locked.id
            )
        )
        or 0
    ) + 1
    job = ProtocolBuildJob(
        public_id=new_public_id("protocol-build"),
        protocol_definition_id=locked.id,
        status="queued",
        attempt_number=attempt,
    )
    locked.build_status = "pending"
    locked.build_error_code = None
    locked.build_error_message = None
    locked.build_started_at = None
    locked.built_at = None
    db.add(job)
    db.flush()
    return job


def _claim_next_job(db: Session) -> tuple[ProtocolBuildJob, ProtocolDefinition] | None:
    job = db.scalar(
        select(ProtocolBuildJob)
        .where(ProtocolBuildJob.status == "queued")
        .order_by(ProtocolBuildJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    definition = db.get(ProtocolDefinition, job.protocol_definition_id)
    if definition is None:
        db.delete(job)
        db.commit()
        return None
    started_at = utcnow()
    job.status = "building"
    job.started_at = started_at
    job.finished_at = None
    job.error_code = None
    job.error_message = None
    job.log_excerpt = None
    definition.build_status = "building"
    definition.build_started_at = started_at
    definition.build_error_code = None
    definition.build_error_message = None
    db.commit()
    return job, definition


def recover_stale_protocol_builds(db: Session) -> int:
    cutoff = utcnow() - STALE_BUILD_AFTER
    jobs = list(
        db.scalars(
            select(ProtocolBuildJob).where(
                ProtocolBuildJob.status == "building",
                ProtocolBuildJob.started_at < cutoff,
            )
        ).all()
    )
    for job in jobs:
        definition = db.get(ProtocolDefinition, job.protocol_definition_id)
        job.status = "queued"
        job.started_at = None
        job.error_code = "worker_recovered"
        job.error_message = "构建任务因工作进程中断而重新排队"
        if definition is not None:
            definition.build_status = "pending"
            definition.build_started_at = None
            definition.build_error_code = None
            definition.build_error_message = None
    if jobs:
        db.commit()
    return len(jobs)


def enqueue_legacy_protocol_builds(db: Session) -> int:
    """Backfill definitions created before build jobs became durable."""

    definitions = list(
        db.scalars(
            select(ProtocolDefinition).where(
                ProtocolDefinition.is_builtin.is_(False),
                ProtocolDefinition.build_status.not_in(("ready", "disabled")),
                ~select(ProtocolBuildJob.id)
                .where(
                    ProtocolBuildJob.protocol_definition_id
                    == ProtocolDefinition.id
                )
                .exists(),
            )
        ).all()
    )
    for definition in definitions:
        definition.build_status = "pending"
        queue_protocol_build(db, definition)
    if definitions:
        db.commit()
    return len(definitions)


def process_next_protocol_build(builder: ProtocolBuilder | None = None) -> bool:
    builder = builder or ProtocolBuilderClient()
    with SessionLocal() as db:
        claimed = _claim_next_job(db)
        if claimed is None:
            return False
        job, definition = claimed
        snapshot: dict[str, Any] = {
            "job_id": job.id,
            "definition_db_id": definition.id,
            "definition_id": str(definition.id),
            "adapter_key": definition.adapter_key,
            "package_name": definition.package_name,
            "version": definition.version,
            "contract_version": definition.contract_version,
        }

    try:
        result = builder.build(
            definition_id=snapshot["definition_id"],
            adapter_key=snapshot["adapter_key"],
            package_name=snapshot["package_name"],
            version=snapshot["version"],
            contract_version=snapshot["contract_version"],
        )
    except ProtocolBuilderError as exc:
        final_status = (
            "requires_adaptation"
            if exc.code == "requires_adaptation"
            else "failed"
        )
        with SessionLocal() as db:
            job = db.get(ProtocolBuildJob, snapshot["job_id"])
            definition = db.get(ProtocolDefinition, snapshot["definition_db_id"])
            if job is not None:
                job.status = final_status
                job.error_code = exc.code[:64]
                job.error_message = str(exc)[:1024]
                job.log_excerpt = exc.log_excerpt[:BUILD_LOG_LIMIT] or None
                job.finished_at = utcnow()
            if definition is not None:
                definition.build_status = final_status
                definition.build_error_code = exc.code[:64]
                definition.build_error_message = str(exc)[:1024]
                definition.built_at = None
            db.commit()
        logger.warning(
            "protocol_build_failed",
            extra={
                "definition_id": snapshot["definition_id"],
                "version": snapshot["version"],
                "error_code": exc.code,
            },
        )
        return True
    except Exception as exc:
        logger.exception(
            "protocol_build_unexpected_failure",
            extra={"definition_id": snapshot["definition_id"]},
        )
        failure = ProtocolBuilderError("internal_error", str(exc)[:1024])
        with SessionLocal() as db:
            job = db.get(ProtocolBuildJob, snapshot["job_id"])
            definition = db.get(ProtocolDefinition, snapshot["definition_db_id"])
            if job is not None:
                job.status = "failed"
                job.error_code = failure.code
                job.error_message = str(failure)
                job.finished_at = utcnow()
            if definition is not None:
                definition.build_status = "failed"
                definition.build_error_code = failure.code
                definition.build_error_message = str(failure)
                definition.built_at = None
            db.commit()
        return True

    finished_at = utcnow()
    with SessionLocal() as db:
        job = db.get(ProtocolBuildJob, snapshot["job_id"])
        definition = db.get(ProtocolDefinition, snapshot["definition_db_id"])
        if job is not None:
            job.status = "succeeded"
            job.artifact_digest = result.artifact_digest
            job.artifact_integrity = result.artifact_integrity
            job.log_excerpt = result.log_excerpt or None
            job.finished_at = finished_at
        if definition is not None:
            definition.build_status = "ready"
            definition.artifact_digest = result.artifact_digest
            definition.artifact_integrity = result.artifact_integrity
            definition.build_error_code = None
            definition.build_error_message = None
            definition.built_at = finished_at
        db.commit()
    logger.info(
        "protocol_build_succeeded",
        extra={
            "definition_id": snapshot["definition_id"],
            "version": snapshot["version"],
            "artifact_digest": result.artifact_digest,
        },
    )
    return True


def _protocol_build_loop() -> None:
    with SessionLocal() as db:
        backfilled = enqueue_legacy_protocol_builds(db)
        if backfilled:
            logger.info(
                "legacy_protocol_builds_enqueued", extra={"count": backfilled}
            )
        recovered = recover_stale_protocol_builds(db)
        if recovered:
            logger.warning(
                "stale_protocol_builds_requeued", extra={"count": recovered}
            )
    while True:
        try:
            processed = process_next_protocol_build()
        except Exception:
            logger.exception("protocol_build_worker_iteration_failed")
            processed = False
        threading.Event().wait(0.1 if processed else 2.0)


def start_protocol_build_worker() -> threading.Thread:
    thread = threading.Thread(
        target=_protocol_build_loop,
        name="protocol-build-worker",
        daemon=True,
    )
    thread.start()
    return thread
