from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import UTC, timedelta
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    DomainCreate,
    DomainOrderCreate,
    ProviderDomainImport,
    DomainQuoteRequest,
    DomainSearchRequest,
    DomainUpdate,
)
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.snowflake import new_public_id

from app.models import (
    DomainOrder,
    DomainQuote,
    DomainRecord,
    PromotionChannel,
    SystemCredential,
    SystemPlatformConfiguration,
)
from app.security import decrypt_secret, utcnow
from app.serializers import iso
from app.task_queue import redis_client
from app.services.domain_verify import DomainVerifyError, verify_public_domain
from app.services.domain_onboarding import continue_domain_onboarding
from app.services.domain_registrar import (
    DomainRegistrarError,
    DomainRegistrarUnknownError,
    DomainSearchReport,
    MockDomainRegistrar,
    NameSiloDomainRegistrar,
)
from app.services.platform_clients import (
    CloudflareClient,
    NameSiloClient,
    PlatformClientError,
)
router = APIRouter(prefix="/api/domains", tags=["domains"])
order_router = APIRouter(prefix="/api/domain-orders", tags=["domain-orders"])
logger = logging.getLogger(__name__)
DOMAIN_SEARCH_KEY_PREFIX = "parloq:domain-search:"
DOMAIN_SEARCH_TTL_SECONDS = 15 * 60


def _is_duplicate_quote_order_error(exc: IntegrityError) -> bool:
    """Return whether an integrity error is the quote/order uniqueness conflict."""

    diagnostic = getattr(exc.orig, "diag", None)
    constraint_name = str(
        getattr(diagnostic, "constraint_name", "") or ""
    ).lower()
    if constraint_name in {"domain_orders_quote_id_key", "ix_domain_orders_quote_id"}:
        return True

    message = str(exc.orig).lower()
    return (
        "unique constraint failed: domain_orders.quote_id" in message
        or (
            "duplicate key" in message
            and "domain_orders" in message
            and "quote_id" in message
        )
    )


def _registrar(
    db: DbSession,
    *,
    provider: str | None = None,
) -> MockDomainRegistrar | NameSiloDomainRegistrar:
    if get_settings().domain_registrar_mock:
        if provider not in {None, "mock"}:
            raise HTTPException(status_code=409, detail="订单注册商与当前配置不一致")
        return MockDomainRegistrar()
    if provider not in {None, "namesilo"}:
        raise HTTPException(status_code=409, detail="订单注册商与当前配置不一致")
    config = db.scalar(
        select(SystemPlatformConfiguration).where(
            SystemPlatformConfiguration.platform_key == "namesilo"
        )
    )
    credential = db.scalar(
        select(SystemCredential).where(
            SystemCredential.platform_key == "namesilo",
            SystemCredential.credential_key == "api_key",
        )
    )
    if config is None or not config.enabled or credential is None:
        raise HTTPException(status_code=503, detail="NameSilo 尚未启用或未配置凭据")
    try:
        api_key = decrypt_secret(credential.value_ciphertext)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="NameSilo 凭据无法读取，请重新配置") from exc
    settings = dict(config.settings_json or {})
    payment_id = str(settings.get("paymentId") or "").strip() or None
    if payment_id is None:
        raise HTTPException(
            status_code=503,
            detail="NameSilo 尚未配置信用卡 Payment ID",
        )
    return NameSiloDomainRegistrar(api_key, payment_id=payment_id)


def _close_registrar(registrar: MockDomainRegistrar | NameSiloDomainRegistrar) -> None:
    if isinstance(registrar, NameSiloDomainRegistrar):
        registrar.close()


def _platform_secret(
    db: DbSession,
    platform_key: str,
    credential_key: str,
) -> tuple[str, dict[str, object]]:
    config = db.scalar(
        select(SystemPlatformConfiguration).where(
            SystemPlatformConfiguration.platform_key == platform_key
        )
    )
    credential = db.scalar(
        select(SystemCredential).where(
            SystemCredential.platform_key == platform_key,
            SystemCredential.credential_key == credential_key,
        )
    )
    display_name = "Cloudflare" if platform_key == "cloudflare" else "NameSilo"
    if config is None or not config.enabled or credential is None:
        raise HTTPException(
            status_code=503,
            detail=f"{display_name} 尚未启用或未配置凭据",
        )
    try:
        secret = decrypt_secret(credential.value_ciphertext)
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{display_name} 凭据无法读取，请重新配置",
        ) from exc
    return secret, dict(config.settings_json or {})


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
    onboarding_state = dict(item.onboarding_state_json or {})
    onboarding_attempted_at = item.onboarding_attempted_at
    if onboarding_attempted_at is not None:
        onboarding_attempted_at = onboarding_attempted_at.replace(
            tzinfo=onboarding_attempted_at.tzinfo or UTC
        )
    onboarding_can_continue = item.onboarding_status != "completed" and (
        item.onboarding_status != "running"
        or onboarding_attempted_at is None
        or onboarding_attempted_at <= utcnow() - timedelta(minutes=5)
    )
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
        "onboarding": {
            "status": item.onboarding_status,
            "stage": item.onboarding_stage,
            "message": item.onboarding_message,
            "nameservers": onboarding_state.get("cloudflareNameservers", []),
            "zoneStatus": onboarding_state.get("cloudflareZoneStatus"),
            "canContinue": onboarding_can_continue,
            "lastAttemptedAt": iso(item.onboarding_attempted_at),
            "completedAt": iso(item.onboarding_completed_at),
        },
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
            "provision": item.status in {"paid", "purchase_ready"} or (
                item.status == "failed" and item.provider_order_ref is None
            ),
            "reconcile": can_reconcile,
            "cancel": item.status in {"pending_payment", "paid", "purchase_ready"},
            "delete": item.status in {"failed", "cancelled"}
            and item.provider_order_ref is None
            and item.domain_id is None,
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
                    [
                        "pending_payment",
                        "paid",
                        "purchase_ready",
                        "provisioning",
                        "unknown",
                        "completed",
                    ]
                ),
            )
        )
    )


def _search_state(
    search_id: str,
    owner_user_id: int,
    label: str,
    years: int,
    report: DomainSearchReport,
    *,
    status_value: str,
    occupied_hostnames: frozenset[str] = frozenset(),
    error: str | None = None,
) -> dict:
    options = [
        {
            "domain": item.domain,
            "registrationPrice": float(item.registration_price * years),
            "renewalPrice": (
                float(item.renewal_price) if item.renewal_price is not None else None
            ),
            "currency": "USD",
            "years": years,
        }
        for item in report.options
        if item.domain not in occupied_hostnames
    ]
    return {
        "searchId": search_id,
        "ownerUserId": str(owner_user_id),
        "label": label,
        "years": years,
        "currency": "USD",
        "options": options,
        "status": status_value,
        "partial": report.partial,
        "searchedCount": report.searched_count,
        "skippedCount": report.skipped_count,
        "candidateCount": report.candidate_count,
        "error": error,
        "updatedAt": iso(utcnow()),
    }


def _public_search_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if key != "ownerUserId"}


def _store_search_state(client, state: dict) -> None:
    client.setex(
        f"{DOMAIN_SEARCH_KEY_PREFIX}{state['searchId']}",
        DOMAIN_SEARCH_TTL_SECONDS,
        json.dumps(state, ensure_ascii=False),
    )


def _run_domain_search(
    registrar: NameSiloDomainRegistrar,
    *,
    search_id: str,
    owner_user_id: int,
    label: str,
    years: int,
    occupied_hostnames: frozenset[str],
) -> None:
    client = redis_client()
    latest = DomainSearchReport(options=(), searched_count=0, candidate_count=0)

    def publish(report: DomainSearchReport) -> None:
        nonlocal latest
        latest = report
        _store_search_state(
            client,
            _search_state(
                search_id,
                owner_user_id,
                label,
                years,
                report,
                status_value="running",
                occupied_hostnames=occupied_hostnames,
            ),
        )

    try:
        latest = registrar.search(label, on_progress=publish)
        _store_search_state(
            client,
            _search_state(
                search_id,
                owner_user_id,
                label,
                years,
                latest,
                status_value="completed",
                occupied_hostnames=occupied_hostnames,
            ),
        )
    except (DomainRegistrarError, RedisError, OSError) as exc:
        try:
            _store_search_state(
                client,
                _search_state(
                    search_id,
                    owner_user_id,
                    label,
                    years,
                    latest,
                    status_value="failed",
                    occupied_hostnames=occupied_hostnames,
                    error=str(exc)[:500],
                ),
            )
        except (RedisError, OSError):
            pass
    finally:
        registrar.close()
        client.close()


@router.get("")
def list_domains(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(DomainRecord).where(DomainRecord.archived_at.is_(None))
    if current_user.role != "admin": statement = statement.where(DomainRecord.created_by == current_user.id)
    items = db.scalars(statement.order_by(DomainRecord.created_at.desc())).all()
    return {"data": {"rows": [domain_row(db, item) for item in items], "total": len(items)}}


@router.get("/cloudflare")
def list_cloudflare_domains(db: DbSession, current_user: CurrentUser) -> dict:
    api_token, settings = _platform_secret(db, "cloudflare", "api_token")
    client = CloudflareClient(
        api_token,
        account_id=str(settings.get("accountId") or "").strip() or None,
    )
    try:
        zones = client.list_zones()
        try:
            registrations = client.list_registrations()
        except PlatformClientError:
            # Cloudflare Registrar is optional. A token that can manage Zones and
            # DNS must still be able to use this inventory and onboarding flow.
            registrations = []
    except PlatformClientError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"读取 Cloudflare 域名失败：{exc}",
        ) from exc
    finally:
        client.close()

    domain_statement = select(DomainRecord).where(DomainRecord.archived_at.is_(None))
    if current_user.role != "admin":
        domain_statement = domain_statement.where(DomainRecord.created_by == current_user.id)
    local_domains = db.scalars(domain_statement).all()
    domains_by_hostname = {item.hostname.lower(): item for item in local_domains}
    registrations_by_hostname = {
        str(item.get("domain_name") or "").lower().rstrip("."): item
        for item in registrations
        if str(item.get("domain_name") or "").strip()
    }

    rows = []
    for zone in zones:
        hostname = str(zone.get("name") or "").lower().rstrip(".")
        local_domain = domains_by_hostname.get(hostname)
        registration = registrations_by_hostname.get(hostname, {})
        source = "account_existing"
        if local_domain is not None:
            source = (
                "system_purchase"
                if local_domain.acquisition_type == "purchased"
                else "system_import"
            )
        rows.append(
            {
                "hostname": hostname,
                "status": str(zone.get("status") or "unknown"),
                "paused": bool(zone.get("paused")),
                "source": source,
                "systemDomainId": entity_id(local_domain) if local_domain else None,
                "createdAt": registration.get("created_at"),
                "expiresAt": registration.get("expires_at"),
            }
        )
    rows.sort(key=lambda row: row["hostname"])
    return {"data": {"rows": rows, "total": len(rows)}}


@router.get("/namesilo")
def list_namesilo_domains(db: DbSession, current_user: CurrentUser) -> dict:
    api_key, _ = _platform_secret(db, "namesilo", "api_key")
    client = NameSiloClient(api_key)
    try:
        provider_domains = client.list_domains()
    except PlatformClientError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"读取 NameSilo 域名失败：{exc}",
        ) from exc
    finally:
        client.close()

    order_statement = select(DomainOrder).where(DomainOrder.provider == "namesilo")
    domain_statement = select(DomainRecord).where(DomainRecord.archived_at.is_(None))
    if current_user.role != "admin":
        order_statement = order_statement.where(DomainOrder.created_by == current_user.id)
        domain_statement = domain_statement.where(DomainRecord.created_by == current_user.id)
    orders = db.scalars(order_statement.order_by(DomainOrder.created_at.desc())).all()
    local_domains = db.scalars(domain_statement).all()
    domains_by_hostname = {item.hostname.lower(): item for item in local_domains}

    orders_by_hostname: dict[str, list[DomainOrder]] = {}
    for order in orders:
        orders_by_hostname.setdefault(order.hostname.lower(), []).append(order)

    rows: list[dict[str, object]] = []
    provider_hostnames: set[str] = set()
    for provider_domain in provider_domains:
        hostname = provider_domain["domain"].lower()
        provider_hostnames.add(hostname)
        hostname_orders = orders_by_hostname.get(hostname, [])
        latest_order = hostname_orders[0] if hostname_orders else None
        purchase_order = next(
            (
                order
                for order in hostname_orders
                if order.status == "completed" or order.provider_order_ref is not None
            ),
            None,
        )
        local_domain = domains_by_hostname.get(hostname)
        rows.append(
            {
                "hostname": hostname,
                "source": "system_purchase" if purchase_order else "account_existing",
                "providerOwned": True,
                "providerStatus": "active",
                "createdAt": provider_domain.get("created") or None,
                "expiresAt": provider_domain.get("expires") or None,
                "systemDomainId": entity_id(local_domain) if local_domain else None,
                "order": _order_row(db, latest_order) if latest_order else None,
            }
        )

    for order in orders:
        hostname = order.hostname.lower()
        if hostname in provider_hostnames:
            continue
        local_domain = domains_by_hostname.get(hostname)
        rows.append(
            {
                "hostname": hostname,
                "source": "system_order",
                "providerOwned": False,
                "providerStatus": order.status,
                "createdAt": None,
                "expiresAt": None,
                "systemDomainId": entity_id(local_domain) if local_domain else None,
                "order": _order_row(db, order),
            }
        )

    rows.sort(key=lambda row: str(row["hostname"]))
    return {"data": {"rows": rows, "total": len(rows)}}


@router.post("/provider-import", status_code=status.HTTP_201_CREATED)
def import_provider_domain(
    payload: ProviderDomainImport,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    if not payload.confirm_dns_replace:
        raise HTTPException(
            status_code=422,
            detail="接入前必须确认系统将重建根域名的冲突路由解析",
        )
    existing = db.scalar(
        select(DomainRecord).where(DomainRecord.hostname == payload.hostname)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="该域名已存在于系统中，请在系统域名页继续处理",
        )

    state: dict[str, object] = {
        "sourceProvider": payload.provider,
        "replaceRoutingRecords": True,
        "dnsReplacementConfirmed": True,
    }
    registrar_provider: str | None = None
    if payload.provider == "cloudflare":
        api_token, settings = _platform_secret(db, "cloudflare", "api_token")
        client = CloudflareClient(
            api_token,
            account_id=str(settings.get("accountId") or "").strip() or None,
        )
        try:
            zone = client.find_zone(payload.hostname)
        except PlatformClientError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"核对 Cloudflare 域名失败：{exc}",
            ) from exc
        finally:
            client.close()
        if zone is None:
            raise HTTPException(status_code=409, detail="Cloudflare 当前账户中未找到该域名")
        state.update(
            {
                "cloudflareZoneId": str(zone.get("id") or ""),
                "cloudflareZoneStatus": str(zone.get("status") or "unknown"),
                "cloudflareNameservers": [
                    str(value).lower().rstrip(".")
                    for value in (zone.get("name_servers") or [])
                    if str(value).strip()
                ],
            }
        )
    else:
        api_key, _ = _platform_secret(db, "namesilo", "api_key")
        client = NameSiloClient(api_key)
        try:
            owned = client.owns_domain(payload.hostname)
        except PlatformClientError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"核对 NameSilo 域名失败：{exc}",
            ) from exc
        finally:
            client.close()
        if not owned:
            raise HTTPException(status_code=409, detail="NameSilo 当前账户中未找到该域名")
        registrar_provider = "namesilo"

    item = DomainRecord(
        public_id=new_public_id("dom"),
        hostname=payload.hostname,
        acquisition_type="connected",
        management_mode="platform",
        registrar_provider=registrar_provider,
        registration_status="active",
        hosting_provider="cloudflare",
        hosting_status="pending",
        verification_token=secrets.token_urlsafe(24),
        enabled=True,
        dns_status="untested",
        ssl_status="untested",
        onboarding_state_json=state,
        created_by=current_user.id,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="域名已存在") from None
    db.refresh(item)
    return {"data": {"domain": domain_row(db, item)}}


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
    try:
        registrar = _registrar(db)
    except HTTPException as exc:
        if exc.status_code == 503:
            return {"data": {
                "hostname": normalized,
                "available": None,
                "quote": None,
                "registrarIntegrationConfigured": False,
            }}
        raise
    try:
        quote = registrar.quote(normalized, years)
    except DomainRegistrarError as exc:
        raise HTTPException(status_code=502, detail="域名注册商询价失败") from exc
    finally:
        _close_registrar(registrar)
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


@order_router.post("/search", status_code=status.HTTP_202_ACCEPTED)
def search_domains(
    payload: DomainSearchRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    registrar = _registrar(db)
    search_id = uuid4().hex
    occupied_hostnames = frozenset(
        db.scalars(
            select(DomainRecord.hostname).where(DomainRecord.archived_at.is_(None))
        ).all()
    ) | frozenset(
        db.scalars(
            select(DomainOrder.hostname).where(
                DomainOrder.status.in_(
                    (
                        "pending_payment",
                        "paid",
                        "purchase_ready",
                        "provisioning",
                        "unknown",
                        "completed",
                    )
                )
            )
        ).all()
    )
    if isinstance(registrar, MockDomainRegistrar):
        state = _search_state(
            search_id,
            current_user.id,
            payload.label,
            payload.years,
            registrar.search(payload.label),
            status_value="completed",
            occupied_hostnames=occupied_hostnames,
        )
        return {"data": {"search": _public_search_state(state)}}

    state = _search_state(
        search_id,
        current_user.id,
        payload.label,
        payload.years,
        DomainSearchReport(options=(), searched_count=0, candidate_count=0),
        status_value="running",
        occupied_hostnames=occupied_hostnames,
    )
    client = redis_client()
    try:
        _store_search_state(client, state)
    except (RedisError, OSError) as exc:
        registrar.close()
        raise HTTPException(status_code=503, detail="域名查询任务暂时不可用") from exc
    finally:
        client.close()
    background_tasks.add_task(
        _run_domain_search,
        registrar,
        search_id=search_id,
        owner_user_id=current_user.id,
        label=payload.label,
        years=payload.years,
        occupied_hostnames=occupied_hostnames,
    )
    return {"data": {"search": _public_search_state(state)}}


@order_router.get("/search/{search_id}")
def get_domain_search(search_id: str, current_user: CurrentUser) -> dict:
    if re.fullmatch(r"[0-9a-f]{32}", search_id) is None:
        raise HTTPException(status_code=404, detail="域名查询不存在或已过期")
    client = redis_client()
    try:
        raw = client.get(f"{DOMAIN_SEARCH_KEY_PREFIX}{search_id}")
    except (RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail="域名查询任务暂时不可用") from exc
    finally:
        client.close()
    if not raw:
        raise HTTPException(status_code=404, detail="域名查询不存在或已过期")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="域名查询状态无法读取") from exc
    if str(state.get("ownerUserId")) != str(current_user.id):
        raise HTTPException(status_code=404, detail="域名查询不存在或已过期")
    return {"data": {"search": _public_search_state(state)}}


@order_router.post("/quote", status_code=status.HTTP_201_CREATED)
def create_domain_quote(
    payload: DomainQuoteRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    if _hostname_occupied(db, payload.hostname):
        raise HTTPException(status_code=409, detail="域名不可购买或已有进行中的订单")
    registrar = _registrar(db)
    try:
        registrar_quote = registrar.quote(payload.hostname, payload.years)
    except DomainRegistrarError as exc:
        raise HTTPException(status_code=502, detail="NameSilo 询价失败") from exc
    finally:
        _close_registrar(registrar)
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
        status=("pending_payment" if quote.provider == "mock" else "purchase_ready"),
        provider=quote.provider,
        auto_renew=payload.auto_renew,
        created_by=current_user.id,
    )
    db.add(item)
    quote.consumed_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_quote_order_error(exc):
            raise HTTPException(
                status_code=409,
                detail="报价已被使用，请勿重复创建订单",
            ) from None
        logger.exception("Unexpected integrity error while creating a domain order")
        raise HTTPException(status_code=500, detail="创建订单失败，请稍后重试") from exc
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
    if item.paid_at is None:
        item.paid_at = now
    item.completed_at = now
    return domain


@order_router.post("/{order_id}/provision")
def provision_domain_order(
    order_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    item = _order(db, order_id, current_user)
    registrar = _registrar(db, provider=item.provider)
    transitioned = db.execute(
        update(DomainOrder)
        .where(
            DomainOrder.id == item.id,
            DomainOrder.status.in_(("paid", "purchase_ready", "failed")),
            or_(
                DomainOrder.status != "failed",
                DomainOrder.provider_order_ref.is_(None),
            ),
        )
        .values(status="provisioning", failure_reason=None, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        db.rollback()
        _close_registrar(registrar)
        raise HTTPException(
            status_code=409,
            detail="只有待购买或确定失败且未生成注册商订单号的订单可以开通",
        )
    db.commit()
    db.refresh(item)
    provider_order_ref: str | None = None
    try:
        current_quote = registrar.quote(item.hostname, item.years)
        if not current_quote.available:
            raise DomainRegistrarError("域名已不可购买")
        if current_quote.amount != item.amount:
            raise DomainRegistrarError("域名价格已变化，请重新询价")
        result = registrar.register(
            item.hostname,
            item.years,
            private=True,
            auto_renew=item.auto_renew,
        )
        provider_order_ref = result.provider_order_ref
        if result.amount is not None:
            item.amount = result.amount
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
        failed.failure_reason = str(exc)[:1000]
        db.commit()
        raise HTTPException(status_code=422, detail=failed.failure_reason) from exc
    finally:
        _close_registrar(registrar)
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
    registrar = _registrar(db, provider=item.provider)
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
        _close_registrar(registrar)
        raise HTTPException(status_code=409, detail="订单正在被其他对账任务处理")
    db.commit()
    db.refresh(item)
    try:
        result = registrar.reconcile(item.provider_order_ref, item.hostname)
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
    finally:
        _close_registrar(registrar)
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
            DomainOrder.status.in_(("pending_payment", "paid", "purchase_ready")),
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


@order_router.delete("/{order_id}")
def delete_domain_order(
    order_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _order(db, order_id, current_user)
    if (
        item.status not in {"failed", "cancelled"}
        or item.provider_order_ref is not None
        or item.domain_id is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="仅可删除没有注册商订单号、也未生成域名的失败或已取消订单",
        )
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}


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
        item.onboarding_status = "idle"; item.onboarding_stage = "not_started"; item.onboarding_state_json = {}; item.onboarding_message = None; item.onboarding_attempted_at = None; item.onboarding_completed_at = None
    if payload.enabled is not None: item.enabled = payload.enabled
    if payload.management_mode is not None: item.management_mode = payload.management_mode
    if payload.auto_renew is not None:
        if item.acquisition_type != "purchased": raise HTTPException(status_code=400, detail="接入域名不支持自动续费")
        item.auto_renew = payload.auto_renew
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(status_code=409, detail="域名已存在") from None
    return {"data": {"domain": domain_row(db, item)}}


@router.post("/{domain_id}/onboarding/continue")
def continue_onboarding(
    domain_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _domain(db, domain_id, current_user)
    if item.onboarding_status == "completed":
        return {"data": {"domain": domain_row(db, item)}}
    stale_before = utcnow() - timedelta(minutes=5)
    claimed = db.execute(
        update(DomainRecord)
        .where(
            DomainRecord.id == item.id,
            or_(
                DomainRecord.onboarding_status != "running",
                DomainRecord.onboarding_attempted_at.is_(None),
                DomainRecord.onboarding_attempted_at <= stale_before,
            ),
        )
        .values(
            onboarding_status="running",
            onboarding_attempted_at=utcnow(),
            onboarding_message="正在核对平台配置",
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="域名接入流程正在执行，请勿重复提交")
    db.commit()
    db.refresh(item)
    item = continue_domain_onboarding(db, item)
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
        if item.onboarding_status != "idle":
            item.onboarding_status = "completed"; item.onboarding_stage = "completed"; item.onboarding_message = "域名已通过公网验证"; item.onboarding_completed_at = utcnow()
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
