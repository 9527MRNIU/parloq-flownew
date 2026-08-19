from __future__ import annotations

import logging
import re
from datetime import timedelta
from pathlib import Path
from pathlib import PurePosixPath

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
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
    verify_integration_embed_token,
)
from app.services.promotion_event_rate_limits import (
    PromotionEventRateLimitRequest,
    PromotionEventRateLimitUnavailable,
    consume_promotion_event_rate_limits,
    normalized_promotion_event_rate_limit_policy,
)
from app.services.public_rate_limits import public_request_ip
from app.snowflake import new_public_id, parse_snowflake_id
from app.validation import parse_public_datetime


router = APIRouter(prefix="/api/promotion/integrations", tags=["promotion-integrations"])
public_router = APIRouter(
    prefix="/api/public/promotion/integrations",
    tags=["public-promotion-integrations"],
)
PUBLIC_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "public"
logger = logging.getLogger(__name__)


def _integration(
    db: DbSession,
    identifier: str,
    user,
) -> PromotionIntegration:
    statement = select(PromotionIntegration).where(
        identifier_filter(PromotionIntegration, identifier),
        PromotionIntegration.archived_at.is_(None),
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
        DomainRecord.archived_at.is_(None),
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


def integration_row(db: DbSession, item: PromotionIntegration) -> dict:
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
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


@router.get("")
def list_integrations(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PromotionIntegration).where(
        PromotionIntegration.archived_at.is_(None)
    )
    if current_user.role != "admin":
        statement = statement.where(PromotionIntegration.created_by == current_user.id)
    items = db.scalars(
        statement.order_by(PromotionIntegration.updated_at.desc())
    ).all()
    return {
        "data": {
            "rows": [integration_row(db, item) for item in items],
            "total": len(items),
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
        select(PromotionIntegrationEvent, PromotionChannel.slug)
        .join(PromotionChannel, PromotionChannel.id == PromotionIntegrationEvent.channel_id)
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
                {
                    "id": entity_id(event),
                    "eventType": event.event_type,
                    "channelId": entity_id(event.channel_id),
                    "channelSlug": channel_slug,
                    "templateId": (
                        entity_id(event.template_id) if event.template_id else None
                    ),
                    "integrationVersion": event.integration_version,
                    "visitorId": event.visitor_id,
                    "fingerprintQuality": event.fingerprint_quality,
                    "trafficSource": event.traffic_source,
                    "occurredAt": iso(event.occurred_at),
                    "metadata": event.metadata_json or {},
                    "createdAt": iso(event.created_at),
                }
                for event, channel_slug in event_rows
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


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=403, detail="缺少集成运行会话")
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=403, detail="集成运行会话无效")
    return token


def _public_runtime_context(
    db: DbSession,
    integration_id: str,
    request: Request,
    token: str,
) -> tuple[
    PromotionIntegration,
    DomainRecord,
    PromotionChannel,
    PromotionTemplate,
    dict,
]:
    row = db.execute(
        select(PromotionIntegration, DomainRecord)
        .join(DomainRecord, DomainRecord.id == PromotionIntegration.source_domain_id)
        .where(
            identifier_filter(PromotionIntegration, integration_id),
            PromotionIntegration.integration_type == "iframe",
            PromotionIntegration.enabled.is_(True),
            PromotionIntegration.archived_at.is_(None),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404)
    item, domain = row
    request_host = (request.url.hostname or "").lower().rstrip(".")
    if request_host != domain.hostname or not domain_is_ready(domain):
        raise HTTPException(status_code=404)
    payload = verify_integration_embed_token(token)
    try:
        channel_id = parse_snowflake_id(payload.get("channel"))
        template_id = parse_snowflake_id(payload.get("template"))
        tenant_id = parse_snowflake_id(payload.get("tenant"))
    except ValueError:
        raise HTTPException(status_code=403, detail="集成运行会话已失效") from None
    if (
        payload.get("integration") != entity_id(item)
        or payload.get("version") != item.version
        or tenant_id != item.created_by
    ):
        raise HTTPException(status_code=403, detail="集成运行会话已失效")
    channel = db.get(PromotionChannel, channel_id)
    template = db.get(PromotionTemplate, template_id)
    binding = db.scalar(
        select(PromotionTemplateIntegration).where(
            PromotionTemplateIntegration.template_id == template_id,
            PromotionTemplateIntegration.integration_id == item.id,
            PromotionTemplateIntegration.enabled.is_(True),
        )
    )
    feedback_enabled, _ = integration_feedback_contract(item)
    if (
        not feedback_enabled
        or channel is None
        or channel.archived_at is not None
        or channel.status != "active"
        or channel.template_id != template_id
        or channel.created_by != item.created_by
        or template is None
        or template.archived_at is not None
        or template.created_by != item.created_by
        or binding is None
    ):
        raise HTTPException(status_code=403, detail="集成运行会话已失效")
    return item, domain, channel, template, payload


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


@public_router.get("/{integration_id}/runtime")
def public_integration_runtime(
    integration_id: str,
    request: Request,
    db: DbSession,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = _bearer_token(authorization)
    item, _, channel, template, payload = _public_runtime_context(
        db, integration_id, request, token
    )
    policy = db.scalar(
        select(PromotionTemplatePolicy).where(
            PromotionTemplatePolicy.created_by == item.created_by
        )
    )
    _, feedback_events = integration_feedback_contract(item)
    return JSONResponse(
        {
            "data": {
                "integration": {
                    "id": entity_id(item),
                    "key": item.integration_key,
                    "version": item.version,
                },
                "channel": {
                    "id": entity_id(channel),
                    "slug": channel.slug,
                    "countryCode": channel.country_code,
                    "trafficSource": payload.get("trafficSource", "direct"),
                },
                "template": {
                    "id": entity_id(template),
                    "version": template.version,
                },
                "eventUrl": f"/api/public/promotion/integrations/{entity_id(item)}/events",
                "sessionToken": token,
                "sessionExpiresAt": int(payload["exp"]),
                "fingerprintEnabled": (
                    (policy.device_signals if policy else "fingerprint")
                    == "fingerprint"
                ),
                "events": list(feedback_events),
                "visitorStorageKey": (
                    f"promotion_integration_visitor:{entity_id(item)}:{entity_id(channel)}"
                ),
            }
        },
        headers={"Cache-Control": "no-store"},
    )


@public_router.post("/{integration_id}/events")
async def report_integration_event(
    integration_id: str,
    request: Request,
    db: DbSession,
) -> JSONResponse:
    try:
        event_input = PromotionIntegrationEventInput.model_validate_json(
            await request.body()
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=422, detail=error.errors(include_url=False)
        ) from None
    item, _, channel, template, token_payload = _public_runtime_context(
        db,
        integration_id,
        request,
        event_input.session_token,
    )
    _, allowed_events = integration_feedback_contract(item)
    if event_input.event_type not in allowed_events:
        raise HTTPException(status_code=422, detail="集成没有声明这个回传事件")
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
                    "sessionReports", str(token_payload["nonce"])
                ),
                PromotionEventRateLimitRequest(
                    "ipReports",
                    source_ip
                    if source_ip != "unknown"
                    else f"session:{token_payload['nonce']}",
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
    occurred_ts = int(occurred_at.timestamp())
    if (
        occurred_ts < int(token_payload["iat"]) - 300
        or occurred_ts > int(token_payload["exp"]) + 300
        or occurred_at > now + timedelta(minutes=5)
    ):
        raise HTTPException(status_code=422, detail="occurredAt 超出集成运行会话有效窗口")

    from app.services.device_fingerprints import (
        fingerprint_identity,
        fingerprint_metadata,
    )

    fingerprint_payload = (
        event_input.device_fingerprint
        if (policy.device_signals if policy else "fingerprint") == "fingerprint"
        else None
    )
    fingerprint = fingerprint_identity(item.created_by, fingerprint_payload)
    fingerprint_details = fingerprint_metadata(fingerprint, fingerprint_payload)
    existing = db.scalar(
        select(PromotionIntegrationEvent).where(
            PromotionIntegrationEvent.integration_id == item.id,
            PromotionIntegrationEvent.channel_id == channel.id,
            PromotionIntegrationEvent.idempotency_key
            == event_input.idempotency_key,
        )
    )
    if existing is not None:
        if (
            fingerprint is not None
            and fingerprint_details is not None
            and existing.visitor_fingerprint_hash is None
            and existing.visitor_id == event_input.visitor_id
        ):
            existing.visitor_fingerprint_hash = fingerprint.fingerprint_hash
            existing.fingerprint_version = fingerprint.version
            existing.fingerprint_quality = fingerprint.quality
            metadata = dict(existing.metadata_json or {})
            metadata["deviceFingerprint"] = fingerprint_details
            existing.metadata_json = metadata
            db.commit()
        return JSONResponse(
            {"data": {"ok": True, "duplicate": True}},
            headers={"Cache-Control": "no-store"},
        )
    metadata = dict(event_input.metadata)
    if fingerprint_details is not None:
        metadata["deviceFingerprint"] = fingerprint_details
    event = PromotionIntegrationEvent(
        public_id=new_public_id("piev"),
        integration_id=item.id,
        channel_id=channel.id,
        template_id=template.id,
        integration_version=item.version,
        event_type=event_input.event_type,
        idempotency_key=event_input.idempotency_key,
        visitor_id=event_input.visitor_id,
        visitor_fingerprint_hash=(
            fingerprint.fingerprint_hash if fingerprint else None
        ),
        fingerprint_version=fingerprint.version if fingerprint else None,
        fingerprint_quality=fingerprint.quality if fingerprint else None,
        traffic_source=str(token_payload.get("trafficSource", "direct")),
        occurred_at=occurred_at,
        country_code=channel.country_code,
        metadata_json=metadata,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(
            select(PromotionIntegrationEvent).where(
                PromotionIntegrationEvent.integration_id == item.id,
                PromotionIntegrationEvent.channel_id == channel.id,
                PromotionIntegrationEvent.idempotency_key
                == event_input.idempotency_key,
            )
        )
        if duplicate is None:
            raise
        return JSONResponse(
            {"data": {"ok": True, "duplicate": True}},
            headers={"Cache-Control": "no-store"},
        )
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
            PromotionIntegration.archived_at.is_(None),
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
            raise HTTPException(status_code=500, detail="iframe 入口不是 UTF-8 HTML") from None
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
