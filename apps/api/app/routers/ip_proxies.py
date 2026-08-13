from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import AccountProxyBinding, IpAllocationPolicy, PersonalAccount, ProxyEndpoint
from app.schemas import (
    AccountProxyBindingCreate,
    AccountProxyBindingUpdate,
    ProxyEndpointCreate,
    ProxyEndpointUpdate,
    IpAllocationPolicyUpdate,
)
from app.security import encrypt_secret, utcnow
from app.serializers import account_proxy_binding_row, proxy_endpoint_row
from app.services.proxy_health import ProxyHealthError, check_public_tcp_reachability
from app.services.wa_gateway import GatewayError, WaGatewayClient


router = APIRouter(tags=["ip-proxies"])


def _policy_row(item: IpAllocationPolicy) -> dict:
    return {
        "id": item.public_id,
        "allocationMode": item.allocation_mode,
        "countryMatch": item.country_match,
        "maxAccountsPerIp": item.max_accounts_per_ip,
        "avoidUnhealthy": item.avoid_unhealthy,
        "stickyBinding": item.sticky_binding,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


def _owner_policy(db: DbSession, owner_id: int) -> IpAllocationPolicy:
    item = db.scalar(
        select(IpAllocationPolicy).where(IpAllocationPolicy.created_by == owner_id)
    )
    if item is None:
        item = IpAllocationPolicy(
            public_id=f"ipp_{uuid4().hex}",
            allocation_mode="least_load",
            country_match="prefer",
            max_accounts_per_ip=100,
            avoid_unhealthy=True,
            sticky_binding=True,
            created_by=owner_id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
    return item


@router.get("/api/ip-allocation-policy")
def get_ip_allocation_policy(db: DbSession, current_user: CurrentUser) -> dict:
    return {"data": {"policy": _policy_row(_owner_policy(db, current_user.id))}}


@router.patch("/api/ip-allocation-policy")
def update_ip_allocation_policy(
    payload: IpAllocationPolicyUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _owner_policy(db, current_user.id)
    item.allocation_mode = payload.allocation_mode
    item.country_match = payload.country_match
    item.max_accounts_per_ip = payload.max_accounts_per_ip
    item.avoid_unhealthy = payload.avoid_unhealthy
    item.sticky_binding = payload.sticky_binding
    db.commit()
    db.refresh(item)
    return {"data": {"policy": _policy_row(item)}}


def _proxy_or_404(db: DbSession, public_id: str, user=None) -> ProxyEndpoint:
    statement = select(ProxyEndpoint).where(
            ProxyEndpoint.public_id == public_id,
            ProxyEndpoint.archived_at.is_(None),
        )
    if user is not None and user.role != "admin":
        statement = statement.join(AccountProxyBinding).join(
            PersonalAccount,
            PersonalAccount.public_id == AccountProxyBinding.account_public_id,
        ).where(PersonalAccount.created_by == user.id)
    proxy = db.scalar(statement)
    if proxy is None:
        raise HTTPException(status_code=404, detail="代理 IP 不存在")
    return proxy


def _binding_or_404(db: DbSession, public_id: str, user=None) -> AccountProxyBinding:
    statement = select(AccountProxyBinding).where(AccountProxyBinding.public_id == public_id)
    if user is not None and user.role != "admin":
        statement = statement.join(
            PersonalAccount,
            PersonalAccount.public_id == AccountProxyBinding.account_public_id,
        ).where(PersonalAccount.created_by == user.id)
    binding = db.scalar(statement)
    if binding is None:
        raise HTTPException(status_code=404, detail="代理绑定不存在")
    return binding


def _assigned_count(db: DbSession, proxy_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(AccountProxyBinding)
            .where(AccountProxyBinding.proxy_id == proxy_id)
        )
        or 0
    )


def _sync_account_proxy(db: DbSession, account_public_id: str) -> None:
    """Push a committed-to-be binding into the connection data plane.

    A legacy/external accountPublicId can still be recorded by the IP v1 API;
    only real personal accounts owned by this control plane have a Baileys gateway
    record to update.
    """
    account = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.public_id == account_public_id,
            PersonalAccount.archived_at.is_(None),
        )
    )
    if account is None or not account.phone_e164:
        return
    # Import locally to avoid making proxy serialization depend on the account
    # router at import time.
    from app.routers.personal_accounts import _proxy_url

    WaGatewayClient().update_proxy(account_public_id, _proxy_url(db, account_public_id))


@router.get("/api/ip-proxies")
def list_proxies(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    health_status: str | None = Query(default=None, alias="healthStatus"),
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = select(ProxyEndpoint).where(ProxyEndpoint.archived_at.is_(None))
    if current_user.role != "admin":
        statement = statement.join(AccountProxyBinding).join(
            PersonalAccount,
            PersonalAccount.public_id == AccountProxyBinding.account_public_id,
        ).where(PersonalAccount.created_by == current_user.id).distinct()
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                ProxyEndpoint.name.ilike(pattern),
                ProxyEndpoint.host.ilike(pattern),
                ProxyEndpoint.provider.ilike(pattern),
                ProxyEndpoint.country_code.ilike(pattern),
            )
        )
    if health_status and health_status != "all":
        statement = statement.where(ProxyEndpoint.health_status == health_status)
    if enabled is not None:
        statement = statement.where(ProxyEndpoint.enabled.is_(enabled))
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    proxies = list(
        db.scalars(
            statement.order_by(ProxyEndpoint.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    counts = {
        int(proxy_id): int(count)
        for proxy_id, count in db.execute(
            select(AccountProxyBinding.proxy_id, func.count(AccountProxyBinding.id))
            .where(AccountProxyBinding.proxy_id.in_([proxy.id for proxy in proxies]))
            .group_by(AccountProxyBinding.proxy_id)
        ).all()
    } if proxies else {}
    return {
        "data": {
            "rows": [proxy_endpoint_row(proxy, counts.get(proxy.id, 0)) for proxy in proxies],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.post("/api/ip-proxies", status_code=status.HTTP_201_CREATED)
def create_proxy(payload: ProxyEndpointCreate, db: DbSession, _admin: AdminUser) -> dict:
    username = (payload.username or "").strip()
    password = (payload.password or "").strip()
    proxy = ProxyEndpoint(
        public_id=f"ipx_{uuid4().hex}",
        name=payload.name,
        protocol=payload.protocol,
        host=payload.host,
        port=payload.port,
        username_ciphertext=encrypt_secret(username) if username else None,
        username_last4=username[-4:] if username else "",
        password_ciphertext=encrypt_secret(password) if password else None,
        password_last4=password[-4:] if password else "",
        country_code=payload.country_code,
        provider=payload.provider or None,
        enabled=payload.enabled,
        health_status="untested",
    )
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return {"data": {"proxy": proxy_endpoint_row(proxy)}}


@router.get("/api/ip-proxies/{public_id}")
def get_proxy(public_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    proxy = _proxy_or_404(db, public_id, current_user)
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.patch("/api/ip-proxies/{public_id}")
def update_proxy(
    public_id: str,
    payload: ProxyEndpointUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    proxy = _proxy_or_404(db, public_id)
    connection_fields = {"protocol", "host", "port", "username", "password"}
    if payload.name is not None:
        proxy.name = payload.name
    if payload.protocol is not None:
        proxy.protocol = payload.protocol
    if payload.host is not None:
        proxy.host = payload.host
    if payload.port is not None:
        proxy.port = payload.port
    if "username" in payload.model_fields_set:
        username = (payload.username or "").strip()
        proxy.username_ciphertext = encrypt_secret(username) if username else None
        proxy.username_last4 = username[-4:] if username else ""
    if "password" in payload.model_fields_set:
        password = (payload.password or "").strip()
        proxy.password_ciphertext = encrypt_secret(password) if password else None
        proxy.password_last4 = password[-4:] if password else ""
    if "country_code" in payload.model_fields_set:
        proxy.country_code = payload.country_code
    if "provider" in payload.model_fields_set:
        proxy.provider = payload.provider or None
    if payload.enabled is not None:
        proxy.enabled = payload.enabled
    if connection_fields & payload.model_fields_set:
        proxy.health_status = "untested"
        proxy.last_checked_at = None
        proxy.last_error = None
    db.commit()
    db.refresh(proxy)
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.delete("/api/ip-proxies/{public_id}")
def archive_proxy(public_id: str, db: DbSession, _admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, public_id)
    if _assigned_count(db, proxy.id):
        raise HTTPException(status_code=409, detail="代理仍绑定个人账号，请先解除绑定")
    proxy.enabled = False
    proxy.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}


@router.post("/api/ip-proxies/{public_id}/test")
def test_proxy(public_id: str, db: DbSession, _admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, public_id)
    proxy.last_checked_at = utcnow()
    try:
        if not get_settings().ip_proxy_mock:
            check_public_tcp_reachability(proxy.host, proxy.port)
        proxy.health_status = "healthy"
        proxy.last_error = None
    except ProxyHealthError as exc:
        proxy.health_status = "unhealthy"
        proxy.last_error = str(exc)[:2000]
    db.commit()
    db.refresh(proxy)
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.get("/api/ip-proxy-bindings")
def list_bindings(
    db: DbSession,
    current_user: CurrentUser,
    account_public_id: str | None = Query(default=None, alias="accountPublicId"),
    proxy_public_id: str | None = Query(default=None, alias="proxyPublicId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = select(AccountProxyBinding)
    if current_user.role != "admin":
        statement = statement.join(
            PersonalAccount,
            PersonalAccount.public_id == AccountProxyBinding.account_public_id,
        ).where(PersonalAccount.created_by == current_user.id)
    if account_public_id:
        statement = statement.where(AccountProxyBinding.account_public_id == account_public_id)
    if proxy_public_id:
        statement = statement.join(ProxyEndpoint).where(
            ProxyEndpoint.public_id == proxy_public_id
        )
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    bindings = db.scalars(
        statement.order_by(AccountProxyBinding.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [account_proxy_binding_row(binding) for binding in bindings],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    }


@router.post("/api/ip-proxy-bindings", status_code=status.HTTP_201_CREATED)
def create_binding(
    payload: AccountProxyBindingCreate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    proxy = _proxy_or_404(db, payload.proxy_public_id)
    if not proxy.enabled:
        raise HTTPException(status_code=409, detail="不能绑定已停用的代理")
    binding = AccountProxyBinding(
        public_id=f"ipb_{uuid4().hex}",
        account_public_id=payload.account_public_id,
        proxy_id=proxy.id,
    )
    db.add(binding)
    try:
        db.flush()
        _sync_account_proxy(db, binding.account_public_id)
        db.commit()
    except GatewayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该个人账号已绑定代理") from None
    db.refresh(binding)
    return {"data": {"binding": account_proxy_binding_row(binding)}}


@router.get("/api/ip-proxy-bindings/{public_id}")
def get_binding(public_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    return {"data": {"binding": account_proxy_binding_row(_binding_or_404(db, public_id, current_user))}}


@router.patch("/api/ip-proxy-bindings/{public_id}")
def update_binding(
    public_id: str,
    payload: AccountProxyBindingUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    binding = _binding_or_404(db, public_id)
    proxy = _proxy_or_404(db, payload.proxy_public_id)
    if not proxy.enabled:
        raise HTTPException(status_code=409, detail="不能绑定已停用的代理")
    binding.proxy_id = proxy.id
    try:
        db.flush()
        _sync_account_proxy(db, binding.account_public_id)
        db.commit()
    except GatewayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from None
    db.refresh(binding)
    return {"data": {"binding": account_proxy_binding_row(binding)}}


@router.delete("/api/ip-proxy-bindings/{public_id}")
def delete_binding(public_id: str, db: DbSession, _admin: AdminUser) -> dict:
    binding = _binding_or_404(db, public_id)
    account_public_id = binding.account_public_id
    db.delete(binding)
    try:
        db.flush()
        _sync_account_proxy(db, account_public_id)
        db.commit()
    except GatewayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"data": {"ok": True}}
