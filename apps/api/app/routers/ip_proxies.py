from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.config import get_settings
from app.snowflake import new_public_id, parse_snowflake_id

from app.models import (
    AccountPairingAttempt,
    AccountProxyBinding,
    IpAllocationPolicy,
    PersonalAccount,
    ProxyEndpoint,
)
from app.schemas import (
    AccountProxyBindingCreate,
    AccountProxyBindingUpdate,
    ProxyBatchRebind,
    ProxyEndpointBulkCreate,
    ProxyEndpointBulkTest,
    ProxyEndpointCreate,
    ProxyEndpointImportConfirm,
    ProxyEndpointImportPreview,
    ProxyEndpointUpdate,
    IpAllocationPolicyUpdate,
)
from app.security import encrypt_secret
from app.serializers import account_proxy_binding_row, proxy_endpoint_row
from app.services.proxy_health import (
    ProxyHealthError,
    ProxyHealthPolicy,
    ProxyProbeResult,
    apply_proxy_health_result,
    probe_proxy,
    proxy_is_quarantined,
)
from app.services.gateway_account_configuration import (
    ensure_gateway_account_configuration,
)
from app.services.wa_gateway import GatewayError, WaGatewayClient


router = APIRouter(tags=["ip-proxies"])
logger = logging.getLogger(__name__)
_IMPORT_PREVIEW_TTL_SECONDS = 15 * 60
_ACTIVE_IMPORT_PREVIEWS: dict[tuple[int, str], threading.Event] = {}
_ACTIVE_IMPORT_PREVIEWS_LOCK = threading.Lock()


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


def _parsed_proxy_fingerprint(parsed: _ParsedProxyLine) -> str:
    canonical = json.dumps(
        [
            parsed.protocol,
            parsed.host.lower(),
            parsed.port,
            parsed.username or "",
            parsed.password or "",
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _issue_import_preview_token(admin_id: int, checks: list[dict]) -> str:
    payload = {
        "adminId": str(admin_id),
        "exp": int(time.time()) + _IMPORT_PREVIEW_TTL_SECONDS,
        "checks": checks,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        get_settings().app_secret_key.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _verify_import_preview_token(token: str, admin_id: int) -> list[dict]:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            get_settings().app_secret_key.encode(),
            encoded.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if payload.get("adminId") != str(admin_id):
            raise ValueError("wrong owner")
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("expired")
        checks = payload.get("checks")
        if not isinstance(checks, list) or not all(
            isinstance(item, dict) for item in checks
        ):
            raise ValueError("invalid checks")
        return checks
    except (
        ValueError,
        TypeError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail="检测结果已失效，请重新检测",
        ) from exc


def _transient_proxy(parsed: _ParsedProxyLine) -> ProxyEndpoint:
    username = (parsed.username or "").strip()
    password = (parsed.password or "").strip()
    return ProxyEndpoint(
        public_id=new_public_id("ipx"),
        name=f"{parsed.protocol.upper()} {parsed.host}:{parsed.port}"[:120],
        protocol=parsed.protocol,
        host=parsed.host,
        port=parsed.port,
        username_ciphertext=encrypt_secret(username) if username else None,
        username_last4=username[-4:] if username else "",
        password_ciphertext=encrypt_secret(password) if password else None,
        password_last4=password[-4:] if password else "",
        enabled=True,
        health_status="untested",
    )


def _run_proxy_probe(proxy: ProxyEndpoint) -> ProxyProbeResult:
    try:
        return probe_proxy(proxy)
    except ProxyHealthError as exc:
        return ProxyProbeResult(
            healthy=False,
            reason_category="proxy_probe_failed",
            error=str(exc)[:500],
        )


def _register_import_preview(admin_id: int, request_id: str) -> threading.Event:
    key = (admin_id, request_id)
    with _ACTIVE_IMPORT_PREVIEWS_LOCK:
        if key in _ACTIVE_IMPORT_PREVIEWS:
            raise HTTPException(status_code=409, detail="相同检测任务正在进行中")
        cancel_event = threading.Event()
        _ACTIVE_IMPORT_PREVIEWS[key] = cancel_event
        return cancel_event


def _finish_import_preview(
    admin_id: int,
    request_id: str,
    cancel_event: threading.Event,
) -> None:
    key = (admin_id, request_id)
    with _ACTIVE_IMPORT_PREVIEWS_LOCK:
        if _ACTIVE_IMPORT_PREVIEWS.get(key) is cancel_event:
            _ACTIVE_IMPORT_PREVIEWS.pop(key, None)


def _cancel_import_preview(admin_id: int, request_id: str) -> bool:
    with _ACTIVE_IMPORT_PREVIEWS_LOCK:
        cancel_event = _ACTIVE_IMPORT_PREVIEWS.get((admin_id, request_id))
        if cancel_event is None:
            return False
        cancel_event.set()
        return True


def _policy_row(item: IpAllocationPolicy) -> dict:
    return {
        "id": entity_id(item),
        "allocationMode": item.allocation_mode,
        "countryMatch": item.country_match,
        "maxAccountsPerIp": item.max_accounts_per_ip,
        "avoidUnhealthy": item.avoid_unhealthy,
        "stickyBinding": item.sticky_binding,
        "failureThreshold": item.failure_threshold,
        "cooldownSeconds": item.cooldown_seconds,
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
            country_match="visitor_country",
            max_accounts_per_ip=100,
            avoid_unhealthy=True,
            sticky_binding=True,
            failure_threshold=2,
            cooldown_seconds=900,
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
    item.failure_threshold = payload.failure_threshold
    item.cooldown_seconds = payload.cooldown_seconds
    db.commit()
    db.refresh(item)
    return {"data": {"policy": _policy_row(item)}}


def _proxy_or_404(db: DbSession, identifier: str, user=None) -> ProxyEndpoint:
    statement = select(ProxyEndpoint).where(
        identifier_filter(ProxyEndpoint, identifier),
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


def _bound_gateway_account_ids(db: DbSession, proxy_id: int) -> list[str]:
    return list(
        db.scalars(
            select(AccountProxyBinding.account_public_id).where(
                AccountProxyBinding.proxy_id == proxy_id
            )
        ).all()
    )


def _disconnect_accounts_best_effort(account_ids: list[str]) -> None:
    client = WaGatewayClient()
    for account_id in account_ids:
        try:
            client.disconnect(account_id)
        except GatewayError:
            logger.warning(
                "Failed to disconnect gateway account %s after proxy cooldown",
                account_id,
            )


def _sync_account_proxy(db: DbSession, account_public_id: str) -> None:
    """Push the authoritative account runtime configuration to the gateway.

    A legacy/external accountPublicId can still be recorded by the IP v1 API;
    only real personal accounts owned by this control plane have a Baileys gateway
    record to update.
    """
    account = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.public_id == account_public_id,
            PersonalAccount.deleted_at.is_(None),
        )
    )
    if account is None or not account.phone_e164:
        return
    ensure_gateway_account_configuration(db, account)


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
                PersonalAccount.deleted_at.is_(None),
            )
        )
    return db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.id == account_id,
            PersonalAccount.deleted_at.is_(None),
        )
    )


def _binding_row(db: DbSession, binding: AccountProxyBinding) -> dict:
    account = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.public_id == binding.account_public_id,
            PersonalAccount.deleted_at.is_(None),
        )
    )
    return account_proxy_binding_row(
        binding,
        str(account.id) if account is not None else None,
        account.name if account is not None else None,
        account.phone_e164 if account is not None else None,
    )


def _latest_visitor_country_code(
    db: DbSession, account_id: int
) -> str | None:
    return db.scalar(
        select(AccountPairingAttempt.visitor_country_code)
        .where(
            AccountPairingAttempt.account_id == account_id,
            AccountPairingAttempt.visitor_country_code.is_not(None),
        )
        .order_by(AccountPairingAttempt.created_at.desc())
        .limit(1)
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
    statement = select(ProxyEndpoint)
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


@router.post("/api/ip-proxies/import-preview")
def preview_proxy_import(
    payload: ProxyEndpointImportPreview,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    request_id = payload.request_id or uuid4().hex
    cancel_event = _register_import_preview(admin.id, request_id)
    try:
        return _preview_proxy_import(payload, db, admin, cancel_event)
    finally:
        _finish_import_preview(admin.id, request_id, cancel_event)


@router.post("/api/ip-proxies/import-preview/stream")
def stream_proxy_import(
    payload: ProxyEndpointImportPreview,
    db: DbSession,
    admin: AdminUser,
) -> StreamingResponse:
    request_id = payload.request_id or uuid4().hex
    existing_keys = _proxy_import_existing_keys(db)
    cancel_event = _register_import_preview(admin.id, request_id)

    def event_stream() -> Iterator[str]:
        try:
            for event in _preview_proxy_import_events(
                payload,
                existing_keys,
                admin.id,
                cancel_event,
            ):
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        except HTTPException as exc:
            yield json.dumps(
                {
                    "type": "error",
                    "status": exc.status_code,
                    "detail": exc.detail,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n"
        except Exception:
            logger.exception("Proxy import preview stream failed")
            yield json.dumps(
                {"type": "error", "status": 500, "detail": "代理检测失败"},
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n"
        finally:
            cancel_event.set()
            _finish_import_preview(admin.id, request_id, cancel_event)

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/ip-proxies/import-preview/{request_id}/cancel")
def cancel_proxy_import_preview(request_id: str, admin: AdminUser) -> dict:
    if (
        len(request_id) < 16
        or len(request_id) > 80
        or not all(character.isalnum() or character == "-" for character in request_id)
    ):
        raise HTTPException(status_code=422, detail="检测任务 ID 无效")
    return {
        "data": {
            "ok": True,
            "cancelled": _cancel_import_preview(admin.id, request_id),
        }
    }


def _proxy_import_existing_keys(db: DbSession) -> set[tuple[str, str, int]]:
    return {
        (proxy.protocol.lower(), proxy.host.lower(), proxy.port)
        for proxy in db.scalars(select(ProxyEndpoint)).all()
    }


def _preview_proxy_import_events(
    payload: ProxyEndpointImportPreview,
    existing_keys: set[tuple[str, str, int]],
    admin_id: int,
    cancel_event: threading.Event,
) -> Iterator[dict]:
    seen_keys: set[tuple[str, str, int]] = set()
    results: list[dict] = []
    candidates: list[tuple[int, _ParsedProxyLine, ProxyEndpoint]] = []

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
                    "protocol": parsed.protocol,
                    "host": parsed.host,
                    "port": parsed.port,
                }
            )
            continue
        seen_keys.add(key)
        result_index = len(results)
        results.append(
            {
                "line": line_number,
                "status": "checking",
                "protocol": parsed.protocol,
                "host": parsed.host,
                "port": parsed.port,
            }
        )
        candidates.append((result_index, parsed, _transient_proxy(parsed)))

    if not results:
        raise HTTPException(status_code=422, detail="请至少填写一行代理配置")

    yield {
        "type": "snapshot",
        "results": [dict(item) for item in results],
    }

    probe_results: dict[int, ProxyProbeResult] = {}
    if candidates:
        if cancel_event.is_set():
            raise HTTPException(status_code=409, detail="代理检测已取消")

        def run(proxy: ProxyEndpoint) -> ProxyProbeResult | None:
            if cancel_event.is_set():
                return None
            return _run_proxy_probe(proxy)

        with ThreadPoolExecutor(max_workers=min(10, len(candidates))) as executor:
            future_items = {
                executor.submit(run, proxy): result_index
                for result_index, _parsed, proxy in candidates
            }
            for future in as_completed(future_items):
                probe = future.result()
                if probe is None:
                    continue
                result_index = future_items[future]
                probe_results[result_index] = probe
                country_code = payload.country_code or probe.country_code
                results[result_index].update(
                    {
                        "status": "checked",
                        "healthStatus": "healthy" if probe.healthy else "unhealthy",
                        "countryCode": country_code,
                        "latencyMs": probe.latency_ms,
                        "error": probe.error,
                    }
                )
                yield {"type": "result", "result": dict(results[result_index])}

    if cancel_event.is_set():
        raise HTTPException(status_code=409, detail="代理检测已取消")

    signed_checks: list[dict] = []
    for result_index, parsed, _proxy in candidates:
        probe = probe_results[result_index]
        country_code = results[result_index].get("countryCode")
        signed_checks.append(
            {
                "line": results[result_index]["line"],
                "fingerprint": _parsed_proxy_fingerprint(parsed),
                "healthy": probe.healthy,
                "latencyMs": probe.latency_ms,
                "reasonCategory": probe.reason_category,
                "error": probe.error,
                "countryCode": country_code,
            }
        )

    healthy_count = sum(
        item.get("healthStatus") == "healthy" for item in results
    )
    unhealthy_count = sum(
        item.get("healthStatus") == "unhealthy" for item in results
    )
    yield {
        "type": "complete",
        "data": {
            "previewToken": _issue_import_preview_token(admin_id, signed_checks),
            "results": results,
            "summary": {
                "total": len(results),
                "candidates": len(candidates),
                "healthy": healthy_count,
                "unhealthy": unhealthy_count,
                "duplicate": sum(item["status"] == "duplicate" for item in results),
                "failed": sum(item["status"] == "failed" for item in results),
            },
        }
    }


def _preview_proxy_import(
    payload: ProxyEndpointImportPreview,
    db: DbSession,
    admin: AdminUser,
    cancel_event: threading.Event,
) -> dict:
    existing_keys = _proxy_import_existing_keys(db)
    for event in _preview_proxy_import_events(
        payload,
        existing_keys,
        admin.id,
        cancel_event,
    ):
        if event.get("type") == "complete":
            return {"data": event["data"]}
    raise RuntimeError("proxy import preview ended without a completion event")


@router.post("/api/ip-proxies/import-confirm", status_code=status.HTTP_201_CREATED)
def confirm_proxy_import(
    payload: ProxyEndpointImportConfirm,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    checks = _verify_import_preview_token(payload.preview_token, admin.id)
    checks_by_line = {int(item.get("line") or 0): item for item in checks}
    if len(checks_by_line) != len(checks):
        raise HTTPException(status_code=409, detail="检测结果已失效，请重新检测")

    existing_keys = {
        (proxy.protocol.lower(), proxy.host.lower(), proxy.port)
        for proxy in db.scalars(select(ProxyEndpoint)).all()
    }
    seen_keys: set[tuple[str, str, int]] = set()
    consumed_check_lines: set[int] = set()
    results: list[dict] = []
    created: list[tuple[int, ProxyEndpoint]] = []
    policy_row = _owner_policy(db, admin.id)
    policy = ProxyHealthPolicy(
        failure_threshold=policy_row.failure_threshold,
        cooldown_seconds=policy_row.cooldown_seconds,
    )

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
        check = checks_by_line.get(line_number)
        if check is not None:
            if check.get("fingerprint") != _parsed_proxy_fingerprint(parsed):
                raise HTTPException(
                    status_code=409,
                    detail="代理内容已变化，请重新检测",
                )
            consumed_check_lines.add(line_number)

        if key in existing_keys or key in seen_keys:
            results.append(
                {
                    "line": line_number,
                    "status": "duplicate",
                    "reason": "相同协议、主机和端口的代理已存在",
                }
            )
            continue
        seen_keys.add(key)

        if check is None:
            raise HTTPException(
                status_code=409,
                detail="代理内容已变化，请重新检测",
            )
        healthy = bool(check.get("healthy"))
        if payload.import_mode == "healthy" and not healthy:
            results.append(
                {
                    "line": line_number,
                    "status": "skipped",
                    "reason": "代理检测异常，未导入",
                }
            )
            continue

        username = (parsed.username or "").strip()
        password = (parsed.password or "").strip()
        proxy = ProxyEndpoint(
            public_id=new_public_id("ipx"),
            name=f"{parsed.protocol.upper()} {parsed.host}:{parsed.port}"[:120],
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
        apply_proxy_health_result(
            proxy,
            ProxyProbeResult(
                healthy=healthy,
                latency_ms=(
                    int(check["latencyMs"])
                    if isinstance(check.get("latencyMs"), (int, float))
                    else None
                ),
                reason_category=str(
                    check.get("reasonCategory") or "proxy_probe_failed"
                )[:64],
                error=(str(check["error"])[:500] if check.get("error") else None),
                country_code=(
                    str(check["countryCode"])[:2]
                    if check.get("countryCode")
                    else None
                ),
            ),
            source="import",
            policy=policy,
            direct_probe=True,
        )
        result_index = len(results)
        results.append({"line": line_number, "status": "created"})
        created.append((result_index, proxy))

    if consumed_check_lines != set(checks_by_line):
        raise HTTPException(status_code=409, detail="代理内容已变化，请重新检测")

    if created:
        db.add_all([proxy for _index, proxy in created])
        db.flush()
        for result_index, proxy in created:
            results[result_index]["proxyId"] = entity_id(proxy)
        db.commit()

    created_rows = [
        proxy_endpoint_row(proxy) for _result_index, proxy in created
    ]
    return {
        "data": {
            "rows": created_rows,
            "results": results,
            "summary": {
                "total": len(results),
                "created": len(created_rows),
                "skipped": sum(item["status"] == "skipped" for item in results),
                "duplicate": sum(item["status"] == "duplicate" for item in results),
                "failed": sum(item["status"] == "failed" for item in results),
            },
        }
    }


@router.post("/api/ip-proxies/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_proxies(
    payload: ProxyEndpointBulkCreate,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    existing_keys = {
        (proxy.protocol.lower(), proxy.host.lower(), proxy.port)
        for proxy in db.scalars(
            select(ProxyEndpoint)
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
    connection_changed = bool(connection_fields & payload.model_fields_set)
    bound_account_ids = _bound_gateway_account_ids(db, proxy.id) if connection_changed else []
    if connection_changed:
        proxy.health_status = "untested"
        proxy.last_checked_at = None
        proxy.last_error = None
        proxy.consecutive_failures = 0
        proxy.cooldown_until = None
        proxy.last_success_at = None
        proxy.last_failure_at = None
        proxy.last_check_source = None
        proxy.latency_ms = None
    db.commit()
    db.refresh(proxy)
    if connection_changed:
        # A live Baileys socket cannot swap its transport. Disconnect first,
        # then push the repaired configuration while preserving the session.
        _disconnect_accounts_best_effort(bound_account_ids)
        for account_public_id in bound_account_ids:
            try:
                _sync_account_proxy(db, account_public_id)
            except GatewayError:
                logger.warning(
                    "Failed to synchronize edited proxy to gateway account %s",
                    account_public_id,
                )
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.delete("/api/ip-proxies/{proxy_id}")
def delete_proxy(proxy_id: str, db: DbSession, _admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, proxy_id)
    if _assigned_count(db, proxy.id):
        raise HTTPException(status_code=409, detail="代理仍绑定个人账号，请先解除绑定")
    db.delete(proxy)
    db.commit()
    return {"data": {"ok": True}}


@router.post("/api/ip-proxies/{proxy_id}/test")
def test_proxy(proxy_id: str, db: DbSession, admin: AdminUser) -> dict:
    proxy = _proxy_or_404(db, proxy_id)
    policy_row = _owner_policy(db, admin.id)
    policy = ProxyHealthPolicy(
        failure_threshold=policy_row.failure_threshold,
        cooldown_seconds=policy_row.cooldown_seconds,
    )
    try:
        result = probe_proxy(proxy)
    except ProxyHealthError as exc:
        result = ProxyProbeResult(
            healthy=False,
            reason_category="proxy_probe_failed",
            error=str(exc)[:2000],
        )
    transition = apply_proxy_health_result(
        proxy,
        result,
        source="manual",
        policy=policy,
        direct_probe=True,
    )
    affected_accounts = (
        _bound_gateway_account_ids(db, proxy.id)
        if transition.entered_cooldown
        else []
    )
    db.commit()
    _disconnect_accounts_best_effort(affected_accounts)
    db.refresh(proxy)
    return {"data": {"proxy": proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))}}


@router.post("/api/ip-proxies/test-batch")
def test_proxies_batch(
    payload: ProxyEndpointBulkTest,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    identifiers = list(dict.fromkeys(payload.proxy_ids))
    proxies: list[ProxyEndpoint] = []
    for identifier in identifiers:
        proxies.append(_proxy_or_404(db, identifier))
    policy_row = _owner_policy(db, admin.id)
    policy = ProxyHealthPolicy(
        failure_threshold=policy_row.failure_threshold,
        cooldown_seconds=policy_row.cooldown_seconds,
    )

    results: dict[int, ProxyProbeResult] = {}

    def run(item: ProxyEndpoint) -> ProxyProbeResult:
        try:
            return probe_proxy(item)
        except ProxyHealthError as exc:
            return ProxyProbeResult(
                healthy=False,
                reason_category="proxy_probe_failed",
                error=str(exc)[:2000],
            )

    with ThreadPoolExecutor(max_workers=min(10, len(proxies))) as executor:
        future_items = {executor.submit(run, proxy): proxy for proxy in proxies}
        for future in as_completed(future_items):
            proxy = future_items[future]
            results[proxy.id] = future.result()

    for proxy in proxies:
        apply_proxy_health_result(
            proxy,
            results[proxy.id],
            source=payload.source,
            policy=policy,
            direct_probe=True,
        )
    db.commit()
    for proxy in proxies:
        db.refresh(proxy)
    return {
        "data": {
            "rows": [
                proxy_endpoint_row(proxy, _assigned_count(db, proxy.id))
                for proxy in proxies
            ],
            "summary": {
                "total": len(proxies),
                "healthy": sum(results[item.id].healthy for item in proxies),
                "unhealthy": sum(not results[item.id].healthy for item in proxies),
            },
        }
    }


@router.post("/api/ip-proxy-bindings/rebind-batch")
def rebind_proxy_accounts_batch(
    payload: ProxyBatchRebind,
    db: DbSession,
    _admin: AdminUser,
) -> dict:
    source_proxies: list[ProxyEndpoint] = []
    source_ids: set[int] = set()
    for identifier in payload.source_proxy_ids:
        proxy = _proxy_or_404(db, identifier)
        if proxy.id not in source_ids:
            source_ids.add(proxy.id)
            source_proxies.append(proxy)

    source_entity_ids = {
        proxy.id: entity_id(proxy) for proxy in source_proxies
    }
    manual_target_ids: dict[int, int] = {}
    if payload.mode == "manual":
        for mapping in payload.mappings:
            source = _proxy_or_404(db, mapping.source_proxy_id)
            if source.id not in source_ids:
                raise HTTPException(
                    status_code=422,
                    detail="手动重绑映射包含未选择的源代理",
                )
            if source.id in manual_target_ids:
                raise HTTPException(
                    status_code=422,
                    detail="同一个源代理不能重复指定目标代理",
                )
            target = _proxy_or_404(db, mapping.target_proxy_id)
            if target.id == source.id:
                raise HTTPException(
                    status_code=409,
                    detail="源代理和目标代理不能相同",
                )
            if not target.enabled:
                raise HTTPException(
                    status_code=409,
                    detail=f"目标代理 {target.host}:{target.port} 已停用",
                )
            if proxy_is_quarantined(target):
                raise HTTPException(
                    status_code=409,
                    detail=f"目标代理 {target.host}:{target.port} 正在冷却或需要修复",
                )
            manual_target_ids[source.id] = target.id

    binding_snapshots = [
        {
            "binding_id": binding_id,
            "account_id": account_id,
            "source_proxy_id": source_proxy_id,
        }
        for binding_id, account_id, source_proxy_id in db.execute(
            select(
                AccountProxyBinding.id,
                PersonalAccount.id,
                AccountProxyBinding.proxy_id,
            )
            .outerjoin(
                PersonalAccount,
                PersonalAccount.public_id
                == AccountProxyBinding.account_public_id,
            )
            .where(AccountProxyBinding.proxy_id.in_(source_ids))
            .order_by(AccountProxyBinding.proxy_id, AccountProxyBinding.id)
        ).all()
    ]
    populated_source_ids = {
        item["source_proxy_id"] for item in binding_snapshots
    }
    if payload.mode == "manual":
        missing_mapping_ids = populated_source_ids - manual_target_ids.keys()
        if missing_mapping_ids:
            missing_sources = ", ".join(
                source_entity_ids[source_id]
                for source_id in sorted(missing_mapping_ids)
            )
            raise HTTPException(
                status_code=422,
                detail=f"请为有账号绑定的源代理选择目标代理：{missing_sources}",
            )

    from app.routers.personal_accounts import (
        _apply_gateway_account,
        _auto_proxy,
    )

    results: list[dict] = []
    migrated = 0
    gateway_client = WaGatewayClient()
    disconnect_states = {"warming", "online_idle", "sending", "draining"}
    for snapshot in binding_snapshots:
        binding_id = int(snapshot["binding_id"])
        source_proxy_id = int(snapshot["source_proxy_id"])
        account_database_id = snapshot["account_id"]
        binding = db.get(AccountProxyBinding, binding_id)
        account = (
            db.get(PersonalAccount, int(account_database_id))
            if account_database_id is not None
            else None
        )
        base_result = {
            "bindingId": str(binding_id),
            "accountId": str(account.id) if account is not None else None,
            "accountName": account.name if account is not None else None,
            "accountPhone": account.phone_e164 if account is not None else None,
            "sourceProxyId": source_entity_ids[source_proxy_id],
        }
        if binding is None or binding.proxy_id != source_proxy_id:
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": None,
                    "error": "账号绑定已发生变化，请刷新后重试",
                }
            )
            continue
        if account is None:
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": None,
                    "error": "账号已不存在，请先清理残留绑定",
                }
            )
            continue
        if account.status == "pairing":
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": None,
                    "error": "账号正在配对，请完成或取消配对后重试",
                }
            )
            continue

        target = None
        if payload.mode == "manual":
            target = db.get(ProxyEndpoint, manual_target_ids[source_proxy_id])
        else:
            target = _auto_proxy(
                db,
                account.created_by,
                account.country_code,
                _latest_visitor_country_code(db, account.id),
                exclude_proxy_ids=source_ids,
            )
        if target is None:
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": None,
                    "error": "没有符合当前分配策略的可用代理",
                }
            )
            continue
        target_entity_id = entity_id(target)
        if not target.enabled or proxy_is_quarantined(target):
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": target_entity_id,
                    "error": "目标代理已停用、正在冷却或需要修复",
                }
            )
            continue

        try:
            if account.status in disconnect_states:
                try:
                    disconnected = gateway_client.disconnect(
                        account.gateway_account_id
                    )
                except GatewayError as exc:
                    if exc.status_code != 404:
                        raise
                else:
                    _apply_gateway_account(
                        account,
                        disconnected or {"state": "linked_offline"},
                    )
            binding.proxy_id = target.id
            db.flush()
            try:
                _sync_account_proxy(db, account.gateway_account_id)
            except GatewayError as exc:
                if exc.status_code != 404:
                    raise
            db.commit()
        except GatewayError as exc:
            _rollback_and_reconcile(db, account.gateway_account_id)
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": target_entity_id,
                    "error": str(exc),
                }
            )
            continue
        except Exception:
            _rollback_and_reconcile(db, account.gateway_account_id)
            logger.exception(
                "Failed to batch rebind account %s from proxy %s",
                account.gateway_account_id,
                source_proxy_id,
            )
            results.append(
                {
                    **base_result,
                    "status": "failed",
                    "targetProxyId": target_entity_id,
                    "error": "重绑失败，请稍后重试",
                }
            )
            continue
        migrated += 1
        results.append(
            {
                **base_result,
                "status": "success",
                "targetProxyId": target_entity_id,
                "error": None,
            }
        )

    return {
        "data": {
            "summary": {
                "sourceProxies": len(source_ids),
                "accounts": len(binding_snapshots),
                "migrated": migrated,
                "failed": len(binding_snapshots) - migrated,
                "emptySources": len(source_ids - populated_source_ids),
            },
            "results": results,
        }
    }


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
    if proxy_is_quarantined(proxy):
        raise HTTPException(status_code=409, detail="代理正在冷却或需要修复，不能绑定账号")
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
    if proxy_is_quarantined(proxy):
        raise HTTPException(status_code=409, detail="代理正在冷却或需要修复，不能绑定账号")
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
        if exc.status_code == 404:
            # The data plane has already lost this account, so clearing its
            # control-plane binding is an idempotent success.
            db.commit()
        else:
            _rollback_and_reconcile(db, account_public_id)
            raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception:
        _rollback_and_reconcile(db, account_public_id)
        raise
    return {"data": {"ok": True}}
