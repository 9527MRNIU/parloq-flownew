from __future__ import annotations

import secrets
from datetime import UTC, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    DomainCreate,
    DomainOrderCreate,
    DomainQuoteRequest,
    DomainUpdate,
)
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.snowflake import new_public_id

from app.models import DomainOrder, DomainQuote, DomainRecord, PromotionChannel
from app.security import utcnow
from app.serializers import iso
from app.services.domain_verify import DomainVerifyError, verify_public_domain
from app.services.domain_registrar import (
    DomainRegistrarError,
    DomainRegistrarUnknownError,
    MockDomainRegistrar,
)


router = APIRouter(prefix="/api/domains", tags=["domains"])
order_router = APIRouter(prefix="/api/domain-orders", tags=["domain-orders"])


def _domain(db: DbSession, identifier: str, user) -> DomainRecord:
    statement = select(DomainRecord).where(
        identifier_filter(DomainRecord, identifier),
        DomainRecord.archived_at.is_(None),
    )
    if user.role != "admin": statement = statement.where(DomainRecord.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="域名不存在")
    return item


def domain_row(db: DbSession, item: DomainRecord) -> dict:
    count = int(db.scalar(select(func.count()).select_from(PromotionChannel).where(PromotionChannel.domain_id == item.id, PromotionChannel.archived_at.is_(None))) or 0)
    selectable = (
        item.enabled
        and item.registration_status == "active"
        and item.dns_status == "verified"
        and item.ssl_status == "verified"
        and item.hosting_status == "active"
    )
    settings = get_settings()
    return {
        "id": entity_id(item),
        "hostname": item.hostname,
        "acquisitionType": item.acquisition_type,
        "managementMode": item.management_mode,
        "registrarProvider": item.registrar_provider,
        "registrationStatus": item.registration_status,
        "expiresAt": iso(item.expires_at),
        "autoRenew": item.auto_renew,
        "hostingProvider": item.hosting_provider,
        "hostingStatus": item.hosting_status,
        "enabled": item.enabled,
        "dnsStatus": item.dns_status,
        "hostnameStatus": item.dns_status,
        "sslStatus": item.ssl_status,
        "lastVerifiedAt": iso(item.last_verified_at),
        "lastError": item.last_error,
        "boundChannelCount": count,
        "channelSelectable": selectable,
        "connection": {
            "routing": "shared-host-and-slug",
            "method": "cname_txt",
            "cname": {"name": item.hostname, "target": settings.promotion_ingress_host},
            "txt": {
                "name": f"_parloq-verify.{item.hostname}",
                "value": f"parloq-verification={item.verification_token}",
            },
        },
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _order(db: DbSession, identifier: str, user) -> DomainOrder:
    statement = select(DomainOrder).where(identifier_filter(DomainOrder, identifier))
    if user.role != "admin":
        statement = statement.where(DomainOrder.created_by == user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="域名订单不存在")
    return item


def _order_row(db: DbSession, item: DomainOrder) -> dict:
    domain = db.get(DomainRecord, item.domain_id) if item.domain_id else None
    updated_at = item.updated_at.replace(tzinfo=item.updated_at.tzinfo or UTC)
    can_reconcile = item.status == "unknown" or (
        item.status == "provisioning"
        and updated_at <= utcnow() - timedelta(minutes=5)
    )
    return {
        "id": entity_id(item),
        "quoteId": str(item.quote_id),
        "hostname": item.hostname,
        "years": item.years,
        "amount": float(item.amount),
        "currency": item.currency,
        "status": item.status,
        "provider": item.provider,
        "autoRenew": item.auto_renew,
        "failureReason": item.failure_reason,
        "paidAt": iso(item.paid_at),
        "completedAt": iso(item.completed_at),
        "lastReconciledAt": iso(item.last_reconciled_at),
        "domainId": entity_id(domain) if domain else None,
        "allowedActions": {
            "mockPayment": item.status == "pending_payment" and get_settings().domain_registrar_mock,
            "provision": item.status == "paid",
            "reconcile": can_reconcile,
            "cancel": item.status in {"pending_payment", "paid"},
        },
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _quote_row(item: DomainQuote) -> dict:
    return {
        "id": entity_id(item),
        "quoteId": entity_id(item),
        "hostname": item.hostname,
        "years": item.years,
        "amount": float(item.amount),
        "currency": item.currency,
        "provider": item.provider,
        "expiresAt": iso(item.expires_at),
        "consumed": item.consumed_at is not None,
    }


def _hostname_occupied(db: DbSession, hostname: str) -> bool:
    return bool(
        db.scalar(
            select(func.count()).select_from(DomainRecord).where(
                DomainRecord.hostname == hostname, DomainRecord.archived_at.is_(None)
            )
        )
        or db.scalar(
            select(func.count()).select_from(DomainOrder).where(
                DomainOrder.hostname == hostname,
                DomainOrder.status.in_(
                    ["pending_payment", "paid", "provisioning", "unknown", "completed"]
                ),
            )
        )
    )


@router.get("")
def list_domains(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(DomainRecord).where(DomainRecord.archived_at.is_(None))
    if current_user.role != "admin": statement = statement.where(DomainRecord.created_by == current_user.id)
    items = db.scalars(statement.order_by(DomainRecord.created_at.desc())).all()
    return {"data": {"rows": [domain_row(db, item) for item in items], "total": len(items)}}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_domain(payload: DomainCreate, db: DbSession, current_user: CurrentUser) -> dict:
    item = DomainRecord(
        public_id=new_public_id("dom"),
        hostname=payload.hostname,
        acquisition_type="connected",
        management_mode=payload.management_mode,
        registration_status="pending",
        hosting_provider="cloudflare",
        hosting_status="pending",
        verification_token=secrets.token_urlsafe(24),
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(item)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(status_code=409, detail="域名已存在") from None
    db.refresh(item)
    return {"data": {"domain": domain_row(db, item)}}


@router.get("/availability")
def domain_availability(
    db: DbSession,
    current_user: CurrentUser,
    hostname: str = Query(min_length=1, max_length=255),
    years: int = Query(default=1, ge=1, le=10),
) -> dict:
    del current_user
    try:
        normalized = DomainQuoteRequest(hostname=hostname, years=years).hostname
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="域名格式不正确") from exc
    if _hostname_occupied(db, normalized):
        return {"data": {"hostname": normalized, "available": False, "quote": None}}
    if not get_settings().domain_registrar_mock:
        return {
            "data": {
                "hostname": normalized,
                "available": None,
                "quote": None,
                "registrarIntegrationConfigured": False,
            }
        }
    quote = MockDomainRegistrar().quote(normalized, years)
    return {
        "data": {
            "hostname": normalized,
            "available": quote.available,
            "quote": {
                "amount": float(quote.amount),
                "currency": quote.currency,
                "years": years,
            }
            if quote.available
            else None,
            "registrarIntegrationConfigured": True,
            "provider": quote.provider,
        }
    }


@order_router.post("/quote", status_code=status.HTTP_201_CREATED)
def create_domain_quote(
    payload: DomainQuoteRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    if not get_settings().domain_registrar_mock:
        raise HTTPException(status_code=503, detail="生产注册商适配器尚未配置")
    if _hostname_occupied(db, payload.hostname):
        raise HTTPException(status_code=409, detail="域名不可购买或已有进行中的订单")
    registrar_quote = MockDomainRegistrar().quote(payload.hostname, payload.years)
    if not registrar_quote.available:
        raise HTTPException(status_code=409, detail="域名已被注册")
    item = DomainQuote(
        public_id=new_public_id("dquote"),
        hostname=payload.hostname,
        years=payload.years,
        amount=registrar_quote.amount,
        currency=registrar_quote.currency,
        provider=registrar_quote.provider,
        expires_at=utcnow() + timedelta(minutes=15),
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"data": {"quote": _quote_row(item)}}


@router.get("/available-for-channels")
def available_for_channels(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(DomainRecord).where(
        DomainRecord.archived_at.is_(None),
        DomainRecord.enabled.is_(True),
        DomainRecord.registration_status == "active",
        DomainRecord.dns_status == "verified",
        DomainRecord.ssl_status == "verified",
        DomainRecord.hosting_status == "active",
    )
    if current_user.role != "admin":
        statement = statement.where(DomainRecord.created_by == current_user.id)
    items = db.scalars(statement.order_by(DomainRecord.hostname)).all()
    return {"data": {"rows": [domain_row(db, item) for item in items], "total": len(items)}}


@router.get("/public-verification/{verification_token}")
def public_domain_routing_proof(
    verification_token: str,
    request: Request,
    db: DbSession,
) -> dict:
    request_host = (request.url.hostname or "").lower().rstrip(".")
    item = db.scalar(
        select(DomainRecord).where(
            DomainRecord.hostname == request_host,
            DomainRecord.verification_token == verification_token,
            DomainRecord.enabled.is_(True),
            DomainRecord.archived_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="域名接入校验不存在")
    return {
        "data": {
            "hostname": item.hostname,
            "proof": "parloq-domain-routing-v1",
        }
    }


@order_router.get("")
def list_domain_orders(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(DomainOrder)
    if current_user.role != "admin":
        statement = statement.where(DomainOrder.created_by == current_user.id)
    items = db.scalars(statement.order_by(DomainOrder.created_at.desc())).all()
    return {"data": {"rows": [_order_row(db, item) for item in items], "total": len(items)}}


@order_router.post("", status_code=status.HTTP_201_CREATED)
def create_domain_order(
    payload: DomainOrderCreate, db: DbSession, current_user: CurrentUser
) -> dict:
    if not get_settings().domain_registrar_mock:
        raise HTTPException(status_code=503, detail="生产注册商适配器尚未配置")
    quote = db.scalar(
        select(DomainQuote).where(
            identifier_filter(DomainQuote, payload.quote_id),
            DomainQuote.created_by == current_user.id,
        )
    )
    if quote is None:
        raise HTTPException(status_code=404, detail="报价不存在")
    quote_expiry = quote.expires_at.replace(tzinfo=quote.expires_at.tzinfo or UTC)
    if quote.consumed_at is not None or quote_expiry <= utcnow():
        raise HTTPException(status_code=409, detail="报价已使用或已过期，请重新询价")
    if _hostname_occupied(db, quote.hostname):
        raise HTTPException(status_code=409, detail="域名不可购买或已有进行中的订单")
    item = DomainOrder(
        public_id=new_public_id("dord"),
        quote_id=quote.id,
        hostname=quote.hostname,
        years=quote.years,
        amount=quote.amount,
        currency=quote.currency,
        status="pending_payment",
        provider=quote.provider,
        auto_renew=payload.auto_renew,
        created_by=current_user.id,
    )
    db.add(item)
    quote.consumed_at = utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="报价已被使用，请勿重复创建订单") from None
    db.refresh(item)
    return {"data": {"order": _order_row(db, item)}}


@order_router.post("/{order_id}/mock-payment")
def mock_pay_domain_order(
    order_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    if not get_settings().domain_registrar_mock:
        raise HTTPException(status_code=404, detail="模拟支付不可用")
    item = _order(db, order_id, current_user)
    transitioned = db.execute(
        update(DomainOrder)
        .where(DomainOrder.id == item.id, DomainOrder.status == "pending_payment")
        .values(status="paid", paid_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="只有待支付订单可以确认支付")
    db.commit()
    db.refresh(item)
    return {"data": {"order": _order_row(db, item)}}


def _complete_order(db: DbSession, item: DomainOrder, provider_order_ref: str) -> DomainRecord:
    now = utcnow()
    domain = DomainRecord(
        public_id=new_public_id("dom"),
        hostname=item.hostname,
        acquisition_type="purchased",
        management_mode="platform",
        registrar_provider=item.provider,
        registration_status="active",
        expires_at=now + timedelta(days=365 * item.years),
        auto_renew=item.auto_renew,
        hosting_provider="cloudflare",
        hosting_status="pending",
        verification_token=secrets.token_urlsafe(24),
        enabled=True,
        dns_status="untested",
        ssl_status="untested",
        created_by=item.created_by,
    )
    db.add(domain)
    db.flush()
    item.provider_order_ref = provider_order_ref
    item.domain_id = domain.id
    item.status = "completed"
    item.completed_at = now
    return domain


@order_router.post("/{order_id}/provision")
def provision_domain_order(
    order_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    item = _order(db, order_id, current_user)
    if item.provider != "mock" or not get_settings().domain_registrar_mock:
        raise HTTPException(status_code=503, detail="注册商异步开通尚未配置")
    transitioned = db.execute(
        update(DomainOrder)
        .where(DomainOrder.id == item.id, DomainOrder.status == "paid")
        .values(status="provisioning", updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="只有已支付订单可以开通")
    db.commit()
    db.refresh(item)
    provider_order_ref: str | None = None
    try:
        result = MockDomainRegistrar().register(item.hostname, item.years)
        provider_order_ref = result.provider_order_ref
        domain = _complete_order(db, item, result.provider_order_ref)
        db.commit()
    except DomainRegistrarUnknownError as exc:
        db.rollback()
        unknown = _order(db, order_id, current_user)
        unknown.status = "unknown"
        unknown.provider_order_ref = exc.provider_order_ref
        unknown.failure_reason = "注册商返回结果未知，必须先对账，禁止重复购买"
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"data": {"order": _order_row(db, unknown)}},
        )
    except IntegrityError as exc:
        db.rollback()
        unknown = _order(db, order_id, current_user)
        unknown.status = "unknown"
        unknown.provider_order_ref = provider_order_ref
        unknown.failure_reason = "注册商可能已完成购买，但本地提交失败；必须先对账"
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"data": {"order": _order_row(db, unknown)}},
        )
    except DomainRegistrarError as exc:
        db.rollback()
        failed = _order(db, order_id, current_user)
        failed.status = "failed"
        failed.failure_reason = "域名开通失败，请稍后重试或联系管理员"
        db.commit()
        raise HTTPException(status_code=502, detail=failed.failure_reason) from exc
    db.refresh(item)
    return {
        "data": {
            "order": _order_row(db, item),
            "domain": domain_row(db, domain),
        }
    }


@order_router.post("/{order_id}/reconcile")
def reconcile_domain_order(
    order_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    item = _order(db, order_id, current_user)
    stale_before = utcnow() - timedelta(minutes=5)
    updated_at = item.updated_at.replace(tzinfo=item.updated_at.tzinfo or UTC)
    stale_provisioning = item.status == "provisioning" and updated_at <= stale_before
    if item.status != "unknown" and not stale_provisioning:
        raise HTTPException(status_code=409, detail="只有结果未知或开通租约超时的订单需要对账")
    if item.provider != "mock" or not get_settings().domain_registrar_mock:
        raise HTTPException(status_code=503, detail="注册商对账适配器尚未配置")
    transitioned = db.execute(
        update(DomainOrder)
        .where(
            DomainOrder.id == item.id,
            or_(
                DomainOrder.status == "unknown",
                and_(
                    DomainOrder.status == "provisioning",
                    DomainOrder.updated_at <= stale_before,
                ),
            ),
        )
        .values(status="provisioning", last_reconciled_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="订单正在被其他对账任务处理")
    db.commit()
    db.refresh(item)
    try:
        result = MockDomainRegistrar().reconcile(item.provider_order_ref, item.hostname)
        domain = _complete_order(db, item, result.provider_order_ref)
        db.commit()
    except (DomainRegistrarError, IntegrityError) as exc:
        db.rollback()
        unknown = _order(db, order_id, current_user)
        unknown.status = "unknown"
        unknown.failure_reason = "注册商对账未完成，禁止重新购买"
        unknown.last_reconciled_at = utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail="注册商对账失败，订单仍保持未知状态") from exc
    return {"data": {"order": _order_row(db, item), "domain": domain_row(db, domain)}}


@order_router.post("/{order_id}/cancel")
def cancel_domain_order(
    order_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    item = _order(db, order_id, current_user)
    transitioned = db.execute(
        update(DomainOrder)
        .where(
            DomainOrder.id == item.id,
            DomainOrder.status.in_(("pending_payment", "paid")),
        )
        .values(status="cancelled", updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="当前订单不能取消")
    db.commit()
    db.refresh(item)
    return {"data": {"order": _order_row(db, item)}}


@router.get("/{domain_id}")
def get_domain(domain_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    return {"data": {"domain": domain_row(db, _domain(db, domain_id, current_user))}}


@router.patch("/{domain_id}")
def update_domain(domain_id: str, payload: DomainUpdate, db: DbSession, current_user: CurrentUser) -> dict:
    item = _domain(db, domain_id, current_user)
    if payload.hostname is not None and payload.hostname != item.hostname:
        if item.acquisition_type == "purchased":
            raise HTTPException(status_code=400, detail="已购买域名不能修改名称")
        item.hostname = payload.hostname; item.registration_status = "pending"; item.dns_status = "untested"; item.ssl_status = "untested"; item.hosting_status = "pending"; item.last_verified_at = None
    if payload.enabled is not None: item.enabled = payload.enabled
    if payload.management_mode is not None: item.management_mode = payload.management_mode
    if payload.auto_renew is not None:
        if item.acquisition_type != "purchased": raise HTTPException(status_code=400, detail="接入域名不支持自动续费")
        item.auto_renew = payload.auto_renew
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(status_code=409, detail="域名已存在") from None
    return {"data": {"domain": domain_row(db, item)}}


@router.post("/{domain_id}/verify")
def verify_domain(domain_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _domain(db, domain_id, current_user); item.last_verified_at = utcnow()
    try:
        settings = get_settings()
        if not settings.domain_verify_mock:
            verify_public_domain(
                item.hostname,
                verification_name=f"_parloq-verify.{item.hostname}",
                verification_value=f"parloq-verification={item.verification_token}",
                cname_target=settings.promotion_ingress_host,
                routing_probe_path=(
                    f"/api/domains/public-verification/{item.verification_token}"
                ),
            )
        item.registration_status = "active"; item.dns_status = "verified"; item.ssl_status = "verified"; item.hosting_status = "active"; item.last_error = None
    except DomainVerifyError as exc:
        item.registration_status = "pending"; item.dns_status = "failed"; item.ssl_status = "failed"; item.hosting_status = "failed"; item.last_error = str(exc)
    db.commit()
    return {"data": {"domain": domain_row(db, item)}}


@router.delete("/{domain_id}")
def archive_domain(domain_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _domain(db, domain_id, current_user)
    if db.scalar(select(func.count()).select_from(PromotionChannel).where(PromotionChannel.domain_id == item.id, PromotionChannel.archived_at.is_(None))):
        raise HTTPException(status_code=409, detail="域名仍绑定推广渠道")
    item.enabled = False; item.archived_at = utcnow(); db.commit()
    return {"data": {"ok": True}}
