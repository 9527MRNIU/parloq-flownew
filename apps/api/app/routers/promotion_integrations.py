from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import PromotionIntegrationCreate, PromotionIntegrationUpdate
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.models import (
    DomainRecord,
    PromotionIntegration,
    PromotionIntegrationAsset,
    PromotionTemplateIntegration,
)
from app.serializers import iso
from app.services.promotion_integrations import (
    MAX_INTEGRATION_ZIP,
    domain_is_ready,
    integration_source_urls,
    parse_integration_package,
    replace_integration_package,
)
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/promotion/integrations", tags=["promotion-integrations"])
public_router = APIRouter(
    prefix="/api/public/promotion/integrations",
    tags=["public-promotion-integrations"],
)


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
    return Response(
        asset.content,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
        },
    )
