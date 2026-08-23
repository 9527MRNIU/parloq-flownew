from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from pathlib import PurePosixPath

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    PromotionIntegrationCreate,
    PromotionIntegrationEventInput,
    PromotionRepositoryIntegrationImport,
    PromotionIntegrationUpdate,
)
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.models import (
    DomainRecord,
    PromotionChannel,
    PromotionIntegration,
    PromotionIntegrationAsset,
    PromotionIntegrationEvent,
    PromotionTemplate,
    PromotionTemplateIntegration,
    PromotionTemplatePolicy,
    PromotionVisitor,
)
from app.security import utcnow
from app.serializers import iso
from app.services.promotion_integrations import (
    MAX_INTEGRATION_ZIP,
    domain_is_ready,
    integration_feedback_contract,
    integration_source_urls,
    parse_integration_package,
    replace_integration_package,
)
from app.services.promotion_event_rate_limits import (
    PromotionEventRateLimitRequest,
    PromotionEventRateLimitUnavailable,
    consume_promotion_event_rate_limits,
    normalized_promotion_event_rate_limit_policy,
)
from app.services.public_rate_limits import public_request_ip
from app.services.request_context import public_request_context
from app.services.request_network import resolve_request_network
from app.services.github_repository import (
    GitHubRemoteArtifact,
    GitHubRepositoryConfigurationError,
    GitHubRepositorySnapshot,
    cached_github_repository_snapshot,
    configured_github_repository_client,
    github_repository_snapshot,
    refresh_github_repository_snapshot,
    remote_artifact_row,
    repository_local_status,
    repository_source_matches_artifact,
    stored_repository_source,
    with_repository_source,
)
from app.services.platform_clients import PlatformClientError
from app.snowflake import new_public_id
from app.validation import PROMOTION_INTEGRATION_EVENT_MAX_BYTES, parse_public_datetime


router = APIRouter(prefix="/api/promotion/integrations", tags=["promotion-integrations"])
public_router = APIRouter(
    prefix="/api/public/promotion/integrations",
    tags=["public-promotion-integrations"],
)
PUBLIC_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "public"
logger = logging.getLogger(__name__)


def _integration_event_metadata_bytes(metadata: dict) -> bytes:
    return json.dumps(
        metadata,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _integration_event_row(
    event: PromotionIntegrationEvent,
    channel_slug: str,
    visitor: PromotionVisitor | None,
    *,
    include_metadata: bool,
) -> dict:
    metadata = event.metadata_json or {}
    encoded_metadata = _integration_event_metadata_bytes(metadata)
    row = {
        "id": entity_id(event),
        "eventType": event.event_type,
        "channelId": entity_id(event.channel_id),
        "channelSlug": channel_slug,
        "templateId": entity_id(event.template_id) if event.template_id else None,
        "integrationVersion": event.integration_version,
        "visitorId": entity_id(visitor) if visitor else None,
        "fingerprintQuality": visitor.fingerprint_quality if visitor else None,
        "trafficSource": event.traffic_source,
        "occurredAt": iso(event.occurred_at),
        "metadataBytes": len(encoded_metadata),
        "metadataSha256": hashlib.sha256(encoded_metadata).hexdigest(),
        "createdAt": iso(event.created_at),
    }
    if include_metadata:
        row["metadata"] = metadata
    return row


def _integration(
    db: DbSession,
    identifier: str,
    user,
) -> PromotionIntegration:
    statement = select(PromotionIntegration).where(
        identifier_filter(PromotionIntegration, identifier),
    )
    if user.role != "admin":
        statement = statement.where(PromotionIntegration.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="集成不存在")
    return item


def _source_domain(db: DbSession, identifier: str, user) -> DomainRecord:
    statement = select(DomainRecord).where(
        identifier_filter(DomainRecord, identifier),
    )
    if user.role != "admin":
        statement = statement.where(DomainRecord.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="源域名不存在")
    if not domain_is_ready(item):
        raise HTTPException(status_code=409, detail="源域名尚未完成 DNS、SSL 和托管验证")
    return item


def _validated_create(
    *,
    integration_key: str,
    name: str,
    description: str | None,
    domain_id: str,
    enabled: bool,
) -> PromotionIntegrationCreate:
    try:
        return PromotionIntegrationCreate(
            integrationKey=integration_key,
            name=name,
            description=description,
            domainId=domain_id,
            enabled=enabled,
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from None


def _uploaded_package(file: UploadFile):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="集成文件必须是 ZIP")
    return parse_integration_package(file.file.read(MAX_INTEGRATION_ZIP + 1))


def _repository_integration(
    db: DbSession,
    user,
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> PromotionIntegration | None:
    statement = select(PromotionIntegration)
    if user.role != "admin":
        statement = statement.where(PromotionIntegration.created_by == user.id)
    items = list(db.scalars(statement).all())
    for item in items:
        source = stored_repository_source(item.manifest_json)
        if repository_source_matches_artifact(source, snapshot, artifact):
            return item
    for item in items:
        if item.integration_key == artifact.integration_key:
            return item
    return None


def _repository_integration_status(
    item: PromotionIntegration | None,
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> str:
    if item is None:
        return "new"
    return repository_local_status(
        item.manifest_json,
        item.version,
        snapshot,
        artifact,
    )


def _repository_http_error(error: PlatformClientError) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_409_CONFLICT
            if isinstance(error, GitHubRepositoryConfigurationError)
            else status.HTTP_502_BAD_GATEWAY
        ),
        detail=str(error),
    )


def _integration_repository_source(
    item: PromotionIntegration,
    snapshot: GitHubRepositorySnapshot | None,
) -> dict | None:
    source = stored_repository_source(item.manifest_json)
    if (
        snapshot is None
        or source.get("provider") != "github"
        or source.get("kind") != "integration"
    ):
        return None
    artifact = next(
        (
            value
            for value in snapshot.artifacts
            if value.kind == "integration"
            and repository_source_matches_artifact(source, snapshot, value)
        ),
        None,
    )
    if artifact is None:
        return None
    return {
        "sequence": artifact.sequence,
        "repository": snapshot.repository,
        "ref": snapshot.ref,
        "localStatus": repository_local_status(
            item.manifest_json,
            item.version,
            snapshot,
            artifact,
        ),
        "remoteVersion": artifact.version,
    }


def integration_row(
    db: DbSession,
    item: PromotionIntegration,
    repository_snapshot: GitHubRepositorySnapshot | None = None,
) -> dict:
    domain = db.get(DomainRecord, item.source_domain_id)
    template_count = int(
        db.scalar(
            select(func.count())
            .select_from(PromotionTemplateIntegration)
            .where(
                PromotionTemplateIntegration.integration_id == item.id,
                PromotionTemplateIntegration.enabled.is_(True),
            )
        )
        or 0
    )
    entrypoints = item.entrypoints_json or []
    source_urls = integration_source_urls(item, domain) if domain else []
    feedback_enabled, feedback_events = integration_feedback_contract(item)
    event_count, last_event_at = db.execute(
        select(
            func.count(PromotionIntegrationEvent.id),
            func.max(PromotionIntegrationEvent.occurred_at),
        ).where(PromotionIntegrationEvent.integration_id == item.id)
    ).one()
    return {
        "id": entity_id(item),
        "integrationKey": item.integration_key,
        "name": item.name,
        "description": item.description,
        "type": item.integration_type,
        "domainId": entity_id(domain) if domain else None,
        "hostname": domain.hostname if domain else None,
        "entrypoints": entrypoints,
        "entryPaths": [
            str(entrypoint.get("path") or "")
            for entrypoint in entrypoints
            if entrypoint.get("path")
        ],
        "sourceUrls": source_urls,
        "version": item.version,
        "assetCount": item.asset_count,
        "totalSize": item.total_size,
        "packageSha256": item.package_sha256,
        "enabled": item.enabled,
        "domainReady": domain_is_ready(domain),
        "templateCount": template_count,
        "feedbackEnabled": feedback_enabled,
        "feedbackEvents": list(feedback_events),
        "eventCount": int(event_count or 0),
        "lastEventAt": iso(last_event_at),
        "repositorySource": _integration_repository_source(
            item,
            repository_snapshot,
        ),
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


@router.get("")
def list_integrations(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PromotionIntegration)
    if current_user.role != "admin":
        statement = statement.where(PromotionIntegration.created_by == current_user.id)
    items = db.scalars(
        statement.order_by(PromotionIntegration.updated_at.desc())
    ).all()
    try:
        cached = cached_github_repository_snapshot(db, kind="integration")
    except PlatformClientError:
        cached = None
    snapshot = cached[0] if cached is not None else None
    return {
        "data": {
            "rows": [integration_row(db, item, snapshot) for item in items],
            "total": len(items),
        }
    }


@router.post("/package-metadata")
def inspect_integration_package(
    _current_user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    package = _uploaded_package(file)
    manifest = package.manifest
    return {
        "data": {
            "metadata": {
                "integrationKey": manifest.get("integrationKey"),
                "name": manifest.get("name"),
                "description": manifest.get("description"),
                "version": package.version,
                "type": package.integration_type,
            }
        }
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_integration(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    integration_key: str = Form(..., alias="integrationKey"),
    name: str = Form(...),
    domain_id: str = Form(..., alias="domainId"),
    description: str | None = Form(default=None),
    enabled: bool = Form(default=True),
) -> dict:
    payload = _validated_create(
        integration_key=integration_key,
        name=name,
        description=description,
        domain_id=domain_id,
        enabled=enabled,
    )
    domain = _source_domain(db, payload.domain_id, current_user)
    package = _uploaded_package(file)
    item = PromotionIntegration(
        public_id=new_public_id("pint"),
        integration_key=payload.integration_key,
        name=payload.name,
        description=payload.description,
        integration_type=package.integration_type,
        source_domain_id=domain.id,
        entrypoints_json=[],
        version=package.version,
        manifest_json={},
        asset_count=0,
        total_size=0,
        package_sha256=package.package_sha256,
        integrities_json={},
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(item)
    try:
        db.flush()
        replace_integration_package(db, item, package)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="集成标识已存在") from None
    db.refresh(item)
    return {"data": {"integration": integration_row(db, item)}}


def _repository_integrations_response(
    db: DbSession,
    current_user: CurrentUser,
    snapshot: GitHubRepositorySnapshot,
    refreshed_at,
    *,
    cache_hit: bool,
) -> dict:
    rows = []
    for artifact in snapshot.artifacts:
        item = _repository_integration(db, current_user, snapshot, artifact)
        rows.append(
            {
                **remote_artifact_row(snapshot, artifact),
                "localStatus": _repository_integration_status(
                    item,
                    snapshot,
                    artifact,
                ),
                "localId": entity_id(item) if item is not None else None,
                "localName": item.name if item is not None else None,
                "localVersion": item.version if item is not None else None,
            }
        )
    return {
        "data": {
            "rows": rows,
            "total": len(rows),
            "repository": snapshot.repository,
            "ref": snapshot.ref,
            "commitSha": snapshot.commit_sha,
            "refreshedAt": iso(refreshed_at),
            "cacheHit": cache_hit,
        }
    }


@router.get("/repository")
def list_repository_integrations(
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    try:
        cached = cached_github_repository_snapshot(db, kind="integration")
        if cached is None:
            snapshot, refreshed_at = refresh_github_repository_snapshot(
                db,
                kind="integration",
            )
            cache_hit = False
        else:
            snapshot, refreshed_at = cached
            cache_hit = True
    except PlatformClientError as error:
        raise _repository_http_error(error) from error
    return _repository_integrations_response(
        db,
        current_user,
        snapshot,
        refreshed_at,
        cache_hit=cache_hit,
    )


@router.post("/repository/refresh")
def refresh_repository_integrations(
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    try:
        snapshot, refreshed_at = refresh_github_repository_snapshot(
            db,
            kind="integration",
        )
    except PlatformClientError as error:
        raise _repository_http_error(error) from error
    return _repository_integrations_response(
        db,
        current_user,
        snapshot,
        refreshed_at,
        cache_hit=False,
    )


@router.post("/repository/{sequence}/import")
def import_repository_integration(
    sequence: str,
    payload: PromotionRepositoryIntegrationImport,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    try:
        snapshot, _refreshed_at = github_repository_snapshot(db, kind="integration")
        artifact = next(
            (value for value in snapshot.artifacts if value.sequence == sequence),
            None,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="远程集成不存在")
        item = _repository_integration(db, current_user, snapshot, artifact)
        item_status = _repository_integration_status(item, snapshot, artifact)
        if item_status == "conflict":
            raise HTTPException(
                status_code=409,
                detail="仓库集成内容已变化，请先修改 integration.json 的 version",
            )
        if item_status == "current" and item is not None:
            return {
                "data": {
                    "action": "unchanged",
                    "integration": integration_row(db, item, snapshot),
                }
            }
        client = configured_github_repository_client(db)
        try:
            raw = client.archive_artifact(artifact)
        finally:
            client.close()
    except PlatformClientError as error:
        raise _repository_http_error(error) from error
    package = parse_integration_package(raw)
    if item is None:
        if payload.domain_id is None:
            raise HTTPException(status_code=422, detail="请选择集成源域名")
        domain = _source_domain(db, payload.domain_id, current_user)
        item = PromotionIntegration(
            public_id=new_public_id("pint"),
            integration_key=str(artifact.integration_key or ""),
            name=artifact.name,
            description=artifact.description,
            integration_type=package.integration_type,
            source_domain_id=domain.id,
            entrypoints_json=[],
            version=package.version,
            manifest_json={},
            asset_count=0,
            total_size=0,
            package_sha256=package.package_sha256,
            integrities_json={},
            enabled=payload.enabled,
            created_by=current_user.id,
        )
        db.add(item)
        action = "added"
    else:
        action = "updated"
    try:
        db.flush()
        replace_integration_package(db, item, package)
        item.manifest_json = with_repository_source(
            item.manifest_json or {},
            snapshot,
            artifact,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="集成标识已存在") from None
    db.refresh(item)
    return {
        "data": {
            "action": action,
            "integration": integration_row(db, item, snapshot),
        }
    }


@router.delete("/{integration_id}")
def delete_integration(
    integration_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _integration(db, integration_id, current_user)
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}


@router.get("/{integration_id}")
def get_integration(
    integration_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    return {
        "data": {
            "integration": integration_row(
                db,
                _integration(db, integration_id, current_user),
            )
        }
    }


@router.get("/{integration_id}/events")
def list_integration_events(
    integration_id: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, alias="perPage", ge=1, le=100),
) -> dict:
    item = _integration(db, integration_id, current_user)
    grouped = db.execute(
        select(
            PromotionIntegrationEvent.event_type,
            func.count(PromotionIntegrationEvent.id),
        )
        .where(PromotionIntegrationEvent.integration_id == item.id)
        .group_by(PromotionIntegrationEvent.event_type)
        .order_by(func.count(PromotionIntegrationEvent.id).desc())
    ).all()
    total = sum(int(count) for _, count in grouped)
    event_rows = db.execute(
        select(PromotionIntegrationEvent, PromotionChannel.slug, PromotionVisitor)
        .join(PromotionChannel, PromotionChannel.id == PromotionIntegrationEvent.channel_id)
        .outerjoin(
            PromotionVisitor,
            PromotionVisitor.id == PromotionIntegrationEvent.promotion_visitor_id,
        )
        .where(PromotionIntegrationEvent.integration_id == item.id)
        .order_by(
            PromotionIntegrationEvent.occurred_at.desc(),
            PromotionIntegrationEvent.id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "data": {
            "rows": [
                _integration_event_row(
                    event,
                    channel_slug,
                    visitor,
                    include_metadata=False,
                )
                for event, channel_slug, visitor in event_rows
            ],
            "summary": [
                {"eventType": event_type, "count": int(count)}
                for event_type, count in grouped
            ],
            "total": total,
            "page": page,
            "perPage": per_page,
        }
    }


@router.get("/{integration_id}/events/{event_id}")
def get_integration_event(
    integration_id: str,
    event_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _integration(db, integration_id, current_user)
    row = db.execute(
        select(PromotionIntegrationEvent, PromotionChannel.slug, PromotionVisitor)
        .join(PromotionChannel, PromotionChannel.id == PromotionIntegrationEvent.channel_id)
        .outerjoin(
            PromotionVisitor,
            PromotionVisitor.id == PromotionIntegrationEvent.promotion_visitor_id,
        )
        .where(
            PromotionIntegrationEvent.integration_id == item.id,
            identifier_filter(PromotionIntegrationEvent, event_id),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="回传事件不存在")
    event, channel_slug, visitor = row
    return {
        "data": {
            "event": _integration_event_row(
                event,
                channel_slug,
                visitor,
                include_metadata=True,
            )
        }
    }


@router.patch("/{integration_id}")
def update_integration(
    integration_id: str,
    payload: PromotionIntegrationUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _integration(db, integration_id, current_user)
    if payload.integration_key is not None:
        item.integration_key = payload.integration_key
    if payload.name is not None:
        item.name = payload.name
    if "description" in payload.model_fields_set:
        item.description = payload.description
    if payload.domain_id is not None:
        item.source_domain_id = _source_domain(
            db,
            payload.domain_id,
            current_user,
        ).id
    if payload.enabled is not None:
        item.enabled = payload.enabled
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="集成标识已存在") from None
    db.refresh(item)
    return {"data": {"integration": integration_row(db, item)}}


@router.post("/{integration_id}/edit")
def edit_integration(
    integration_id: str,
    db: DbSession,
    current_user: CurrentUser,
    integration_key: str = Form(..., alias="integrationKey"),
    name: str = Form(...),
    domain_id: str = Form(..., alias="domainId"),
    description: str | None = Form(default=None),
    enabled: bool = Form(default=True),
    file: UploadFile | None = File(default=None),
) -> dict:
    item = _integration(db, integration_id, current_user)
    payload = _validated_create(
        integration_key=integration_key,
        name=name,
        description=description,
        domain_id=domain_id,
        enabled=enabled,
    )
    domain = _source_domain(db, payload.domain_id, current_user)
    package = None
    if file is not None and file.filename:
        package = _uploaded_package(file)
        if (
            package.version == item.version
            and package.package_sha256 != item.package_sha256
        ):
            raise HTTPException(
                status_code=409,
                detail="新资源包不能复用当前版本号，请修改 integration.json 的 version",
            )
    item.integration_key = payload.integration_key
    item.name = payload.name
    item.description = payload.description
    item.source_domain_id = domain.id
    item.enabled = payload.enabled
    if package is not None:
        replace_integration_package(db, item, package)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="集成标识已存在") from None
    db.refresh(item)
    return {"data": {"integration": integration_row(db, item)}}


@router.post("/{integration_id}/versions")
def replace_integration_version(
    integration_id: str,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    item = _integration(db, integration_id, current_user)
    package = _uploaded_package(file)
    if package.version == item.version and package.package_sha256 != item.package_sha256:
        raise HTTPException(
            status_code=409,
            detail="新资源包不能复用当前版本号，请修改 integration.json 的 version",
        )
    replace_integration_package(db, item, package)
    db.commit()
    db.refresh(item)
    return {"data": {"integration": integration_row(db, item)}}


def _public_event_context(
    db: DbSession,
    integration_id: str,
    channel_slug: str,
    request: Request,
) -> tuple[
    PromotionIntegration,
    DomainRecord,
    PromotionChannel,
    PromotionTemplate,
]:
    row = db.execute(
        select(PromotionIntegration, DomainRecord)
        .join(DomainRecord, DomainRecord.id == PromotionIntegration.source_domain_id)
        .where(
            identifier_filter(PromotionIntegration, integration_id),
            PromotionIntegration.integration_type == "iframe",
            PromotionIntegration.enabled.is_(True),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404)
    item, domain = row
    request_host = (request.url.hostname or "").lower().rstrip(".")
    if request_host != domain.hostname or not domain_is_ready(domain):
        raise HTTPException(status_code=404)
    channel = db.scalar(
        select(PromotionChannel).where(
            PromotionChannel.created_by == item.created_by,
            PromotionChannel.slug == channel_slug,
            PromotionChannel.status == "active",
        )
    )
    if channel is None:
        raise HTTPException(status_code=404)
    template = db.get(PromotionTemplate, channel.template_id)
    binding = db.scalar(
        select(PromotionTemplateIntegration).where(
            PromotionTemplateIntegration.template_id == channel.template_id,
            PromotionTemplateIntegration.integration_id == item.id,
            PromotionTemplateIntegration.enabled.is_(True),
        )
    )
    feedback_enabled, _ = integration_feedback_contract(item)
    if (
        not feedback_enabled
        or channel.created_by != item.created_by
        or template is None
        or template.created_by != item.created_by
        or binding is None
    ):
        raise HTTPException(status_code=404)
    return item, domain, channel, template


@public_router.get("/runtime.js")
def integration_runtime_script() -> Response:
    return Response(
        (PUBLIC_RUNTIME_DIR / "promotion-integration-frame.js").read_bytes(),
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        },
    )


@public_router.post("/{integration_id}/channels/{channel_slug}/events")
@public_router.post("/{integration_id}/channels/{channel_slug}/fission/events")
async def report_integration_event(
    integration_id: str,
    channel_slug: str,
    request: Request,
    db: DbSession,
) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > PROMOTION_INTEGRATION_EVENT_MAX_BYTES:
                raise HTTPException(status_code=413, detail="集成回传请求不能超过 1 MiB + 64 KiB")
        except ValueError:
            pass
    body = await request.body()
    if len(body) > PROMOTION_INTEGRATION_EVENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="集成回传请求不能超过 1 MiB + 64 KiB")
    try:
        event_input = PromotionIntegrationEventInput.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            ),
        ) from None
    item, _, channel, template = _public_event_context(
        db, integration_id, channel_slug, request
    )
    traffic_source = "fission" if "/fission/" in request.url.path else "direct"
    _, allowed_events = integration_feedback_contract(item)
    if event_input.event_type not in allowed_events:
        raise HTTPException(status_code=422, detail="集成没有声明这个回传事件")
    from app.services.device_fingerprints import (
        fingerprint_metadata,
        resolve_promotion_visitor,
    )

    promotion_visitor, device_identity = resolve_promotion_visitor(
        db,
        tenant_id=item.created_by,
        raw_fingerprint=event_input.device_fingerprint,
    )
    policy = db.scalar(
        select(PromotionTemplatePolicy).where(
            PromotionTemplatePolicy.created_by == item.created_by
        )
    )
    rate_policy = normalized_promotion_event_rate_limit_policy(
        policy.event_rate_limit_policy_json if policy else None
    )
    source_ip = public_request_ip(request)
    try:
        report_limit = consume_promotion_event_rate_limits(
            rate_policy,
            [
                PromotionEventRateLimitRequest(
                    "sessionReports", promotion_visitor.fingerprint_hash
                ),
                PromotionEventRateLimitRequest(
                    "ipReports",
                    source_ip
                    if source_ip != "unknown"
                    else f"visitor:{promotion_visitor.fingerprint_hash}",
                ),
                PromotionEventRateLimitRequest("channelReports", "all"),
            ],
            partition=f"integration:{item.id}:channel:{channel.id}",
        )
    except PromotionEventRateLimitUnavailable:
        logger.warning(
            "promotion event rate-limit store unavailable; allowing report",
            extra={
                "channel_id": channel.id,
                "integration_id": item.id,
                "report_scope": "integration",
            },
        )
    else:
        if not report_limit.allowed:
            return JSONResponse(
                {
                    "error": {
                        "code": "report_rate_limited",
                        "message": "数据上报过于频繁，请稍后再试",
                        "retryable": True,
                        "retryAfterSeconds": report_limit.retry_after_seconds,
                    }
                },
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": str(report_limit.retry_after_seconds),
                    "Access-Control-Expose-Headers": "Retry-After",
                },
            )
    occurred_at = parse_public_datetime(event_input.occurred_at)
    now = utcnow()
    if (
        occurred_at < now - timedelta(minutes=5)
        or occurred_at > now + timedelta(minutes=5)
    ):
        raise HTTPException(status_code=422, detail="occurredAt 超出允许的上报时间范围")
    metadata = dict(event_input.metadata)
    metadata.pop("requestContext", None)
    metadata["deviceFingerprint"] = fingerprint_metadata(device_identity)
    network = resolve_request_network(request)
    event = PromotionIntegrationEvent(
        public_id=new_public_id("piev"),
        integration_id=item.id,
        channel_id=channel.id,
        template_id=template.id,
        integration_version=item.version,
        event_type=event_input.event_type,
        idempotency_key=f"{event_input.event_type}:{new_public_id('evt')}",
        promotion_visitor_id=promotion_visitor.id,
        traffic_source=traffic_source,
        occurred_at=occurred_at,
        country_code=channel.country_code,
        source_ip=network.source_ip,
        visitor_country_code=network.visitor_country_code,
        network_source=network.network_source,
        request_context_json=public_request_context(
            request, network, received_at=now
        ),
        metadata_json=metadata,
    )
    db.add(event)
    db.commit()
    return JSONResponse(
        {"data": {"ok": True, "duplicate": False, "eventId": entity_id(event)}},
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
    )


@public_router.get("/{integration_id}/{version}/{asset_path:path}")
def public_integration_asset(
    integration_id: str,
    version: str,
    asset_path: str,
    request: Request,
    db: DbSession,
) -> Response:
    row = db.execute(
        select(PromotionIntegration, DomainRecord)
        .join(DomainRecord, DomainRecord.id == PromotionIntegration.source_domain_id)
        .where(
            identifier_filter(PromotionIntegration, integration_id),
            PromotionIntegration.version == version,
            PromotionIntegration.enabled.is_(True),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404)
    item, domain = row
    request_host = (request.url.hostname or "").lower().rstrip(".")
    if request_host != domain.hostname or not domain_is_ready(domain):
        raise HTTPException(status_code=404)
    normalized = PurePosixPath(asset_path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise HTTPException(status_code=404)
    asset = db.scalar(
        select(PromotionIntegrationAsset).where(
            PromotionIntegrationAsset.integration_id == item.id,
            PromotionIntegrationAsset.path == normalized.as_posix(),
        )
    )
    if asset is None:
        raise HTTPException(status_code=404)
    content = asset.content
    feedback_enabled, _ = integration_feedback_contract(item)
    iframe_entry = next(
        (
            str(entrypoint.get("path") or "")
            for entrypoint in item.entrypoints_json or []
            if entrypoint.get("path")
        ),
        "",
    )
    if (
        feedback_enabled
        and item.integration_type == "iframe"
        and asset.path == iframe_entry
    ):
        try:
            document = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=500,
                detail="iframe 入口不是 UTF-8 HTML",
            ) from None
        runtime = (
            '<script src="/api/public/promotion/integrations/runtime.js" '
            f'data-integration-id="{entity_id(item)}"></script>'
        )
        head = re.search(r"<head\b[^>]*>", document, re.I)
        document = (
            document[: head.end()] + runtime + document[head.end() :]
            if head
            else runtime + document
        )
        content = document.encode("utf-8")
    return Response(
        content,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
            "Referrer-Policy": "no-referrer",
        },
    )
