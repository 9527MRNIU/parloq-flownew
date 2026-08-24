from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.deps import AdminUser, DbSession
from app.models import SystemCredential, SystemPlatformConfiguration, UserAccount
from app.schemas import SystemPlatformConfigurationUpdate
from app.security import decrypt_secret, encrypt_secret, secret_fingerprint, utcnow
from app.serializers import iso
from app.services.platform_clients import (
    BaoTaClient,
    CloudflareClient,
    NAMESILO_PAYMENT_ACCOUNT_BALANCE,
    NAMESILO_PAYMENT_VERIFIED_CARD,
    NameSiloClient,
    PlatformClientError,
    namesilo_payment_mode,
)
from app.services.github_repository import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_GITHUB_REF,
    GitHubRepositoryClient,
    clear_github_repository_snapshot,
    normalize_github_ref,
    normalize_github_repository,
    normalize_repository_path,
)


router = APIRouter(prefix="/api/system/configuration", tags=["system-configuration"])


DEFAULT_BAOTA_DOMAIN_POLICY = {
    "cdnEnabled": True,
    "ccEnabled": False,
    "chinaBlocked": True,
}


@dataclass(frozen=True)
class PlatformDefinition:
    name: str
    credential_key: str
    credential_label: str
    description: str


PLATFORMS: dict[str, PlatformDefinition] = {
    "namesilo": PlatformDefinition(
        name="NameSilo",
        credential_key="api_key",
        credential_label="API Key",
        description="用于查询、购买和管理 NameSilo 域名。",
    ),
    "cloudflare": PlatformDefinition(
        name="Cloudflare",
        credential_key="api_token",
        credential_label="API Token",
        description="用于管理域名解析、规则和 Workers。",
    ),
    "baota": PlatformDefinition(
        name="宝塔面板",
        credential_key="api_key",
        credential_label="API Key",
        description="用于通过宝塔开放 API 管理站点与反向代理。",
    ),
    "github": PlatformDefinition(
        name="GitHub 仓库",
        credential_key="access_token",
        credential_label="Fine-grained Token",
        description="只读访问私人模板与集成仓库；Token 仅需 Contents: Read 权限。",
    ),
}


def _definition(platform_key: str) -> PlatformDefinition:
    definition = PLATFORMS.get(platform_key)
    if definition is None:
        raise HTTPException(status_code=404, detail="不支持的平台配置")
    return definition


def _credential(db: DbSession, platform_key: str, credential_key: str) -> SystemCredential | None:
    return db.scalar(
        select(SystemCredential).where(
            SystemCredential.platform_key == platform_key,
            SystemCredential.credential_key == credential_key,
        )
    )


def _configuration(
    db: DbSession,
    platform_key: str,
    *,
    create: bool = False,
) -> SystemPlatformConfiguration | None:
    item = db.scalar(
        select(SystemPlatformConfiguration).where(
            SystemPlatformConfiguration.platform_key == platform_key
        )
    )
    if item is None and create:
        item = SystemPlatformConfiguration(platform_key=platform_key)
        db.add(item)
        db.flush()
    return item


def _platform_row(db: DbSession, platform_key: str, definition: PlatformDefinition) -> dict:
    credential = _credential(db, platform_key, definition.credential_key)
    config = _configuration(db, platform_key)
    actor_id = config.updated_by if config and config.updated_by else (
        credential.updated_by if credential else None
    )
    actor = db.get(UserAccount, actor_id) if actor_id else None
    settings = dict(config.settings_json or {}) if config else {}
    if platform_key == "namesilo":
        settings["paymentMode"] = namesilo_payment_mode(settings.get("paymentMode"))
    elif platform_key == "baota":
        settings["domainPolicy"] = _baota_domain_policy(settings)
        capability = settings.get("nginxFirewallPlugin")
        if not isinstance(capability, dict):
            settings["nginxFirewallPlugin"] = {
                "status": "unknown",
                "checkedAt": None,
            }
    return {
        "key": platform_key,
        "name": definition.name,
        "credentialLabel": definition.credential_label,
        "description": definition.description,
        "configured": credential is not None,
        "maskedValue": f"••••{credential.value_last4}" if credential and credential.value_last4 else None,
        "enabled": bool(config.enabled) if config else False,
        "settings": settings,
        "lastTestStatus": config.last_test_status if config else "untested",
        "lastTestMessage": config.last_test_message if config else None,
        "lastTestAt": iso(config.last_test_at) if config else None,
        "updatedAt": iso(config.updated_at) if config else (iso(credential.updated_at) if credential else None),
        "updatedBy": (actor.display_name or actor.username) if actor is not None else None,
    }


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _baota_domain_policy(settings: dict) -> dict[str, bool]:
    raw = settings.get("domainPolicy")
    current = raw if isinstance(raw, dict) else {}
    return {
        "cdnEnabled": bool(
            current.get("cdnEnabled", DEFAULT_BAOTA_DOMAIN_POLICY["cdnEnabled"])
        ),
        "ccEnabled": bool(
            current.get("ccEnabled", DEFAULT_BAOTA_DOMAIN_POLICY["ccEnabled"])
        ),
        "chinaBlocked": bool(
            current.get(
                "chinaBlocked",
                DEFAULT_BAOTA_DOMAIN_POLICY["chinaBlocked"],
            )
        ),
    }


def _test_sensitive_settings(platform_key: str, settings: dict) -> dict:
    result = dict(settings)
    if platform_key == "baota":
        result.pop("domainPolicy", None)
        result.pop("nginxFirewallPlugin", None)
    return result


def _normalized_settings(
    platform_key: str,
    payload: SystemPlatformConfigurationUpdate,
    current: dict,
) -> dict:
    settings = dict(current)
    if platform_key == "namesilo":
        payment_mode = (
            payload.payment_mode
            if payload.payment_mode is not None
            else namesilo_payment_mode(settings.get("paymentMode"))
        )
        if payload.payment_id is not None:
            payment_id = payload.payment_id.strip()
            if payment_id and not re.fullmatch(r"[0-9]{1,64}", payment_id):
                raise HTTPException(status_code=422, detail="NameSilo 支付 ID 只能包含数字")
            settings["paymentId"] = payment_id
        if payment_mode == NAMESILO_PAYMENT_VERIFIED_CARD and not settings.get("paymentId"):
            raise HTTPException(
                status_code=422,
                detail="使用已验证信用卡支付时必须填写 NameSilo Payment ID",
            )
        settings["paymentMode"] = payment_mode
    elif platform_key == "cloudflare" and payload.account_id is not None:
        settings["accountId"] = payload.account_id.strip()
    elif platform_key == "baota":
        if payload.base_url is not None:
            base_url = payload.base_url.strip().rstrip("/")
            parsed = urlsplit(base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise HTTPException(status_code=422, detail="宝塔面板地址格式不正确")
            settings["baseUrl"] = base_url
        policy = _baota_domain_policy(settings)
        if payload.firewall_cdn_enabled is not None:
            policy["cdnEnabled"] = payload.firewall_cdn_enabled
        if payload.firewall_cc_enabled is not None:
            policy["ccEnabled"] = payload.firewall_cc_enabled
        if payload.firewall_china_blocked is not None:
            policy["chinaBlocked"] = payload.firewall_china_blocked
        if any(
            value is not None
            for value in (
                payload.firewall_cdn_enabled,
                payload.firewall_cc_enabled,
                payload.firewall_china_blocked,
            )
        ):
            settings["domainPolicy"] = policy
    elif platform_key == "github":
        try:
            if payload.repository is not None:
                settings["repository"] = normalize_github_repository(
                    payload.repository
                )
            if payload.repository_ref is not None:
                settings["ref"] = normalize_github_ref(payload.repository_ref)
            if payload.catalog_path is not None:
                settings["catalogPath"] = normalize_repository_path(
                    payload.catalog_path,
                    default=DEFAULT_CATALOG_PATH,
                )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return settings


@router.get("")
def get_system_configuration(response: Response, db: DbSession, _admin: AdminUser) -> dict:
    _no_store(response)
    return {"data": {"platforms": [
        _platform_row(db, platform_key, definition)
        for platform_key, definition in PLATFORMS.items()
    ]}}


@router.put("/{platform_key}")
def set_system_configuration(
    platform_key: str,
    payload: SystemPlatformConfigurationUpdate,
    response: Response,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    definition = _definition(platform_key)
    credential = _credential(db, platform_key, definition.credential_key)
    config = _configuration(db, platform_key, create=True)
    assert config is not None
    changed_secret = False
    if payload.value is not None:
        fingerprint = secret_fingerprint(payload.value)
        if credential is None:
            credential = SystemCredential(
                platform_key=platform_key,
                credential_key=definition.credential_key,
                value_ciphertext=encrypt_secret(payload.value),
                value_fingerprint=fingerprint,
                value_last4=payload.value[-4:],
                updated_by=admin.id,
            )
            db.add(credential)
            changed_secret = True
        elif credential.value_fingerprint != fingerprint:
            credential.value_ciphertext = encrypt_secret(payload.value)
            credential.value_fingerprint = fingerprint
            credential.value_last4 = payload.value[-4:]
            credential.updated_by = admin.id
            changed_secret = True
    current_settings = dict(config.settings_json or {})
    settings = _normalized_settings(platform_key, payload, current_settings)
    configured = credential is not None or payload.value is not None
    enabled = payload.enabled if payload.enabled is not None else config.enabled
    configuration_changed = (
        changed_secret
        or _test_sensitive_settings(platform_key, settings)
        != _test_sensitive_settings(platform_key, current_settings)
        or bool(enabled) != bool(config.enabled)
    )
    if enabled and not configured:
        raise HTTPException(status_code=422, detail="请先配置平台凭据")
    if (
        platform_key == "namesilo"
        and enabled
        and namesilo_payment_mode(settings.get("paymentMode"))
        == NAMESILO_PAYMENT_VERIFIED_CARD
        and not settings.get("paymentId")
    ):
        raise HTTPException(
            status_code=422,
            detail="使用已验证信用卡支付时必须填写 NameSilo Payment ID",
        )
    if platform_key == "baota" and enabled and not settings.get("baseUrl"):
        raise HTTPException(status_code=422, detail="启用宝塔面板前请填写面板地址")
    if platform_key == "github" and enabled and not settings.get("repository"):
        raise HTTPException(status_code=422, detail="启用 GitHub 前请填写私人仓库")
    if platform_key == "github":
        settings.setdefault("ref", DEFAULT_GITHUB_REF)
        settings.setdefault("catalogPath", DEFAULT_CATALOG_PATH)
    config.enabled = bool(enabled)
    config.settings_json = settings
    config.updated_by = admin.id
    if configuration_changed:
        config.last_test_status = "untested"
        config.last_test_message = None
        config.last_test_at = None
        if platform_key == "baota":
            settings["nginxFirewallPlugin"] = {
                "status": "unknown",
                "checkedAt": None,
            }
        if platform_key == "github":
            clear_github_repository_snapshot(db)
    db.commit()
    _no_store(response)
    return {"data": {"platform": _platform_row(db, platform_key, definition)}}


@router.post("/{platform_key}/test")
def test_system_configuration(
    platform_key: str,
    response: Response,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    definition = _definition(platform_key)
    credential = _credential(db, platform_key, definition.credential_key)
    if credential is None:
        raise HTTPException(status_code=409, detail="请先保存平台凭据")
    config = _configuration(db, platform_key, create=True)
    assert config is not None
    settings = dict(config.settings_json or {})
    accounts: list[dict[str, str]] = []
    client: NameSiloClient | CloudflareClient | BaoTaClient | GitHubRepositoryClient | None = None
    try:
        secret = decrypt_secret(credential.value_ciphertext)
        if platform_key == "namesilo":
            payment_mode = namesilo_payment_mode(settings.get("paymentMode"))
            payment_id = (
                str(settings.get("paymentId") or "").strip() or None
                if payment_mode == NAMESILO_PAYMENT_VERIFIED_CARD
                else None
            )
            if payment_mode == NAMESILO_PAYMENT_VERIFIED_CARD and payment_id is None:
                raise PlatformClientError("请先填写 NameSilo 信用卡 Payment ID")
            client = NameSiloClient(secret, payment_id=payment_id)
            client.verify_connection()
            if payment_mode == NAMESILO_PAYMENT_ACCOUNT_BALANCE:
                balance = client.get_account_balance()
                message = f"NameSilo 连接成功，账户余额 USD {balance:.2f}"
            else:
                message = "NameSilo 连接成功；信用卡 Payment ID 将在实际购买时由 NameSilo 校验"
        elif platform_key == "cloudflare":
            client = CloudflareClient(secret)
            accounts = client.verify_connection()
            selected = str(settings.get("accountId") or "")
            ids = {row["id"] for row in accounts}
            if selected and selected not in ids:
                raise PlatformClientError("已保存的 Cloudflare 账户不属于当前 Token")
            if not selected and len(accounts) == 1:
                settings["accountId"] = accounts[0]["id"]
            message = f"Cloudflare 连接成功，发现 {len(accounts)} 个账户"
        elif platform_key == "baota":
            base_url = str(settings.get("baseUrl") or "")
            if not base_url:
                raise PlatformClientError("请先填写宝塔面板地址")
            client = BaoTaClient(base_url, secret)
            client.verify_connection()
            firewall_available = client.nginx_firewall_plugin_available()
            settings["nginxFirewallPlugin"] = {
                "status": "available" if firewall_available else "unavailable",
                "checkedAt": iso(utcnow()),
            }
            message = (
                "宝塔面板连接成功，已检测到 Nginx 防火墙插件"
                if firewall_available
                else "宝塔面板连接成功，未检测到 Nginx 防火墙插件；域名接入时将自动跳过防火墙配置"
            )
        else:
            repository = str(settings.get("repository") or "")
            if not repository:
                raise PlatformClientError("请先填写 GitHub 私人仓库")
            client = GitHubRepositoryClient(
                secret,
                repository=repository,
                ref=str(settings.get("ref") or DEFAULT_GITHUB_REF),
                catalog_path=str(
                    settings.get("catalogPath") or DEFAULT_CATALOG_PATH
                ),
            )
            result = client.verify_connection()
            message = f"GitHub 连接成功：{result['repository']}"
        config.last_test_status = "success"
        config.last_test_message = message
        ok = True
    except (PlatformClientError, ValueError) as exc:
        config.last_test_status = "failed"
        config.last_test_message = str(exc)[:1000]
        message = config.last_test_message
        ok = False
    finally:
        if client is not None:
            client.close()
    config.settings_json = settings
    config.last_test_at = utcnow()
    config.updated_by = admin.id
    db.commit()
    _no_store(response)
    return {"data": {
        "ok": ok,
        "message": message,
        "accounts": accounts,
        "platform": _platform_row(db, platform_key, definition),
    }}


@router.delete("/{platform_key}", status_code=status.HTTP_200_OK)
def clear_system_configuration(
    platform_key: str,
    response: Response,
    db: DbSession,
    admin: AdminUser,
) -> dict:
    definition = _definition(platform_key)
    credential = _credential(db, platform_key, definition.credential_key)
    if credential is not None:
        db.delete(credential)
    config = _configuration(db, platform_key)
    if config is not None:
        db.delete(config)
    if platform_key == "github":
        clear_github_repository_snapshot(db)
    db.commit()
    _no_store(response)
    return {"data": {"cleared": True, "platformKey": platform_key}}
