from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import PromotionIntegrationCreate, PromotionIntegrationUpdate
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.models import (
    DomainRecord,
    PromotionIntegration,
    PromotionTemplateIntegration,
)
from app.serializers import iso
from app.services.promotion_integrations import integration_source_url
from app.snowflake import new_public_id


router = APIRouter(prefix="/api/promotion/integrations", tags=["promotion-integrations"])


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
    if not (
        item.enabled
        and item.registration_status == "active"
        and item.dns_status == "verified"
        and item.ssl_status == "verified"
        and item.hosting_status == "active"
    ):
        raise HTTPException(status_code=409, detail="源域名尚未完成 DNS、SSL 和托管验证")
    return item


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
    domain_ready = bool(
        domain
        and domain.archived_at is None
        and domain.enabled
        and domain.registration_status == "active"
        and domain.dns_status == "verified"
        and domain.ssl_status == "verified"
        and domain.hosting_status == "active"
    )
    return {
        "id": entity_id(item),
        "integrationKey": item.integration_key,
        "name": item.name,
        "description": item.description,
        "type": item.integration_type,
        "domainId": entity_id(domain) if domain else None,
        "hostname": domain.hostname if domain else None,
        "sourcePath": item.source_path,
        "sourceUrl": integration_source_url(item, domain) if domain else None,
        "version": item.version,
        "integrity": item.integrity,
        "enabled": item.enabled,
        "domainReady": domain_ready,
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
    payload: PromotionIntegrationCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    domain = _source_domain(db, payload.domain_id, current_user)
    if payload.integration_type == "iframe" and payload.integrity:
        raise HTTPException(status_code=422, detail="iframe 集成不使用脚本完整性校验")
    item = PromotionIntegration(
        public_id=new_public_id("pint"),
        integration_key=payload.integration_key,
        name=payload.name,
        description=payload.description,
        integration_type=payload.integration_type,
        source_domain_id=domain.id,
        source_path=payload.source_path,
        version=payload.version,
        integrity=payload.integrity,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(item)
    try:
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
    if payload.integration_type is not None:
        item.integration_type = payload.integration_type
    if payload.domain_id is not None:
        item.source_domain_id = _source_domain(
            db, payload.domain_id, current_user
        ).id
    if payload.source_path is not None:
        item.source_path = payload.source_path
    if payload.version is not None:
        item.version = payload.version
    if "integrity" in payload.model_fields_set:
        item.integrity = payload.integrity
    if payload.enabled is not None:
        item.enabled = payload.enabled
    if item.integration_type == "iframe" and item.integrity:
        raise HTTPException(status_code=422, detail="iframe 集成不使用脚本完整性校验")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="集成标识已存在") from None
    db.refresh(item)
    return {"data": {"integration": integration_row(db, item)}}
