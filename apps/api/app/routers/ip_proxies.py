from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.snowflake import new_public_id, parse_snowflake_id

from app.models import AccountProxyBinding, IpAllocationPolicy, PersonalAccount, ProxyEndpoint
from app.schemas import (
    AccountProxyBindingCreate,
    AccountProxyBindingUpdate,
    ProxyEndpointBulkCreate,
    ProxyEndpointCreate,
    ProxyEndpointUpdate,
    IpAllocationPolicyUpdate,
)
from app.security import encrypt_secret, utcnow
from app.serializers import account_proxy_binding_row, proxy_endpoint_row
from app.services.proxy_health import ProxyHealthError, check_public_tcp_reachability
from app.services.wa_gateway import GatewayError, WaGatewayClient


router = APIRouter(tags=["ip-proxies"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedProxyLine:
    protocol: str
    host: str
    port: int
    username: str | None
    password: str | None


def _parse_proxy_line(raw_line: str, default_protocol: str) -> _ParsedProxyLine:
    """Parse one proxy without ever returning or logging the original line."""
    raw = raw_line.strip()
    protocol = default_protocol
    host = ""
    port: int | str = 0
    username: str | None = None
    password: str | None = None

    try:
        simple_parts = raw.split(":", 3)
        is_four_part = (
            "://" not in raw
            and not raw.startswith("[")
            and len(simple_parts) == 4
            and simple_parts[1].isdigit()
        )
        if "://" in raw or (not is_four_part and ("@" in raw or raw.startswith("["))):
            target = raw if "://" in raw else f"//{raw}"
            parsed = urlsplit(target)
            if parsed.scheme:
                protocol = parsed.scheme.lower()
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("代理地址不能包含路径、查询参数或片段")
            host = parsed.hostname or ""
            port = parsed.port or 0
            username = unquote(parsed.username) if parsed.username is not None else None
            password = unquote(parsed.password) if parsed.password is not None else None
        else:
            parts = simple_parts
            if len(parts) not in {2, 4}:
                raise ValueError("格式应为 host:port 或 host:port:用户名:密码")
            host, port = parts[0], parts[1]
            if len(parts) == 4:
                username, password = parts[2], parts[3]
    except (ValueError, UnicodeError) as exc:
        message = str(exc) or "代理格式不正确"
        if "Port could not be cast" in message:
            message = "代理端口必须是 1 到 65535 的整数"
        raise ValueError(message) from None

    if protocol not in {"http", "https", "socks5"}:
        raise ValueError("仅支持 HTTP、HTTPS 和 SOCKS5 协议")
    if not host:
        raise ValueError("代理主机不能为空")
    if not port:
        raise ValueError("代理端口不能为空")

    try:
        validated = ProxyEndpointCreate(
            name="bulk-proxy",
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            password=password,
        )
    except ValidationError as exc:
        message = str(exc.errors()[0].get("msg") or "代理格式不正确")
        raise ValueError(message.removeprefix("Value error, ")) from None
    return _ParsedProxyLine(
        protocol=validated.protocol,
        host=validated.host,
        port=validated.port,
        username=validated.username or None,
        password=validated.password or None,
    )


def _policy_row(item: IpAllocationPolicy) -> dict:
    return {
        "id": entity_id(item),
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
            public_id=new_public_id("ipp"),
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


def _proxy_or_404(db: DbSession, identifier: str, user=None) -> ProxyEndpoint:
    statement = select(ProxyEndpoint).where(
        identifier_filter(ProxyEndpoint, identifier),
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


def _binding_or_404(db: DbSession, identifier: str, user=None) -> AccountProxyBinding:
    try:
        binding_id = parse_snowflake_id(identifier)
    except ValueError:
        raise HTTPException(status_code=404, detail="代理绑定不存在") from None
    statement = select(AccountProxyBinding).where(AccountProxyBinding.id == binding_id)
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


def _reconcile_account_proxy_best_effort(account_public_id: str) -> None:
    """Restore the gateway from the database's final, persisted binding.

    This is deliberately synchronous and best-effort. It only runs after the
    normal binding transaction fails, covering both a definite rollback and an
    ambiguous commit outcome without introducing a durable retry subsystem.
    """
    from app.database import SessionLocal

    try:
        with SessionLocal() as reconcile_db:
            _sync_account_proxy(reconcile_db, account_public_id)
    except Exception:
        logger.exception(
            "Failed to reconcile the persisted proxy binding for gateway account %s",
            account_public_id,
        )


def _rollback_and_reconcile(db: DbSession, account_public_id: str) -> None:
    db.rollback()
    _reconcile_account_proxy_best_effort(account_public_id)


def _binding_account(db: DbSession, identifier: str) -> PersonalAccount | None:
    """Resolve the control-plane Snowflake ID, with legacy gateway IDs read-only."""
    try:
        account_id = parse_snowflake_id(identifier)
    except ValueError:
        return db.scalar(
            select(PersonalAccount).where(
                PersonalAccount.public_id == identifier,
                PersonalAccount.archived_at.is_(None),
            )
        )
    return db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.id == account_id,
            PersonalAccount.archived_at.is_(None),
        )
    )


def _binding_row(db: DbSession, binding: AccountProxyBinding) -> dict:
    account = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.public_id == binding.account_public_id,
            PersonalAccount.archived_at.is_(None),
        )
    )
    return account_proxy_binding_row(
        binding, str(account.id) if account is not None else None
    )


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
        public_id=new_public_id("ipx"),
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


@router.post("/api/ip-proxies/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_proxies(
    payload: ProxyEndpointBulkCreate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    existing_keys = {
        (proxy.protocol.lower(), proxy.host.lower(), proxy.port)
        for proxy in db.scalars(
            select(ProxyEndpoint).where(ProxyEndpoint.archived_at.is_(None))
        ).all()
    }
    seen_keys: set[tuple[str, str, int]] = set()
    results: list[dict] = []
    created: list[ProxyEndpoint] = []
    result_indexes: list[int] = []

    for line_number, raw_line in enumerate(payload.lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parsed = _parse_proxy_line(stripped, payload.default_protocol)
        except ValueError as exc:
            results.append(
                {"line": line_number, "status": "failed", "reason": str(exc)}
            )
            continue

        key = (parsed.protocol, parsed.host.lower(), parsed.port)
        if key in existing_keys or key in seen_keys:
            results.append(
                {
                    "line": line_number,
                    "status": "duplicate",
                    "reason": "相同协议、主机和端口的代理已存在",
                }
            )
            continue

        username = (parsed.username or "").strip()
        password = (parsed.password or "").strip()
        display_name = f"{parsed.protocol.upper()} {parsed.host}:{parsed.port}"[:120]
        proxy = ProxyEndpoint(
            public_id=new_public_id("ipx"),
            name=display_name,
            protocol=parsed.protocol,
            host=parsed.host,
            port=parsed.port,
            username_ciphertext=encrypt_secret(username) if username else None,
            username_last4=username[-4:] if username else "",
            password_ciphertext=encrypt_secret(password) if password else None,
            password_last4=password[-4:] if password else "",
            country_code=payload.country_code,
            provider=payload.provider or None,
            enabled=payload.enabled,
            health_status="untested",
        )
        seen_keys.add(key)
        created.append(proxy)
        result_indexes.append(len(results))
        results.append({"line": line_number, "status": "created"})

    if not results:
        raise HTTPException(status_code=422, detail="请至少填写一行代理配置")

    if created:
        db.add_all(created)
        db.flush()
        created_rows = [proxy_endpoint_row(proxy) for proxy in created]
        for index, proxy in zip(result_indexes, created, strict=True):
            results[index]["proxyId"] = entity_id(proxy)
        db.commit()
    else:
        created_rows = []

    duplicate_count = sum(item["status"] == "duplicate" for item in results)
    failed_count = sum(item["status"] == "failed" for item in results)
    return {
        "data": {
            "rows": created_rows,
            "results": results,
            "summary": {
                "total": len(results),
                "created": len(created_rows),
                "duplicate": duplicate_count,
                "failed": failed_count,
            },
        }
    }


@router.get("/api/ip-proxies/{proxy_id}")
def get_proxy(proxy_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    proxy = _proxy_or_404(db, proxy_id, current_user)
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.patch("/api/ip-proxies/{proxy_id}")
def update_proxy(
    proxy_id: str,
    payload: ProxyEndpointUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    proxy = _proxy_or_404(db, proxy_id)
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


@router.delete("/api/ip-proxies/{proxy_id}")
def archive_proxy(proxy_id: str, db: DbSession, _admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, proxy_id)
    if _assigned_count(db, proxy.id):
        raise HTTPException(status_code=409, detail="代理仍绑定个人账号，请先解除绑定")
    proxy.enabled = False
    proxy.archived_at = utcnow()
    db.commit()
    return {"data": {"ok": True}}


@router.post("/api/ip-proxies/{proxy_id}/test")
def test_proxy(proxy_id: str, db: DbSession, _admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, proxy_id)
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
    account_id: str | None = Query(default=None, alias="accountId"),
    proxy_id: str | None = Query(default=None, alias="proxyId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict:
    statement = select(AccountProxyBinding)
    if current_user.role != "admin":
        statement = statement.join(
            PersonalAccount,
            PersonalAccount.public_id == AccountProxyBinding.account_public_id,
        ).where(PersonalAccount.created_by == current_user.id)
    if account_id:
        account = _binding_account(db, account_id)
        if account is None:
            return {"data": {"rows": [], "total": 0, "page": page, "pageSize": page_size}}
        statement = statement.where(
            AccountProxyBinding.account_public_id == account.gateway_account_id
        )
    if proxy_id:
        statement = statement.join(ProxyEndpoint).where(
            identifier_filter(ProxyEndpoint, proxy_id)
        )
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    bindings = db.scalars(
        statement.order_by(AccountProxyBinding.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [_binding_row(db, binding) for binding in bindings],
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
    proxy = _proxy_or_404(db, payload.proxy_id)
    if not proxy.enabled:
        raise HTTPException(status_code=409, detail="不能绑定已停用的代理")
    account = _binding_account(db, payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="个人账号不存在")
    binding = AccountProxyBinding(
        public_id=new_public_id("ipb"),
        account_public_id=account.gateway_account_id,
        proxy_id=proxy.id,
    )
    db.add(binding)
    try:
        db.flush()
        _sync_account_proxy(db, binding.account_public_id)
        db.commit()
    except GatewayError as exc:
        _rollback_and_reconcile(db, binding.account_public_id)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except IntegrityError:
        _rollback_and_reconcile(db, binding.account_public_id)
        raise HTTPException(status_code=409, detail="该个人账号已绑定代理") from None
    except Exception:
        _rollback_and_reconcile(db, binding.account_public_id)
        raise
    db.refresh(binding)
    return {"data": {"binding": _binding_row(db, binding)}}


@router.get("/api/ip-proxy-bindings/{binding_id}")
def get_binding(binding_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    return {"data": {"binding": _binding_row(db, _binding_or_404(db, binding_id, current_user))}}


@router.patch("/api/ip-proxy-bindings/{binding_id}")
def update_binding(
    binding_id: str,
    payload: AccountProxyBindingUpdate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    binding = _binding_or_404(db, binding_id)
    proxy = _proxy_or_404(db, payload.proxy_id)
    if not proxy.enabled:
        raise HTTPException(status_code=409, detail="不能绑定已停用的代理")
    binding.proxy_id = proxy.id
    try:
        db.flush()
        _sync_account_proxy(db, binding.account_public_id)
        db.commit()
    except GatewayError as exc:
        _rollback_and_reconcile(db, binding.account_public_id)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception:
        _rollback_and_reconcile(db, binding.account_public_id)
        raise
    db.refresh(binding)
    return {"data": {"binding": _binding_row(db, binding)}}


@router.delete("/api/ip-proxy-bindings/{binding_id}")
def delete_binding(binding_id: str, db: DbSession, _admin: AdminUser) -> dict:
    binding = _binding_or_404(db, binding_id)
    account_public_id = binding.account_public_id
    db.delete(binding)
    try:
        db.flush()
        _sync_account_proxy(db, account_public_id)
        db.commit()
    except GatewayError as exc:
        _rollback_and_reconcile(db, account_public_id)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception:
        _rollback_and_reconcile(db, account_public_id)
        raise
    return {"data": {"ok": True}}
