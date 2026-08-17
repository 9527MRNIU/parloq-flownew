from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DomainRecord, SystemCredential, SystemPlatformConfiguration
from app.security import decrypt_secret, utcnow
from app.services.domain_verify import DomainVerifyError, verify_public_domain
from app.services.platform_clients import (
    BaoTaClient,
    CloudflareClient,
    NameSiloClient,
    PlatformClientError,
)


@dataclass(frozen=True)
class _Platform:
    secret: str
    settings: dict[str, object]


def _platform(db: Session, key: str, credential_key: str) -> _Platform:
    labels = {
        "namesilo": "NameSilo",
        "cloudflare": "Cloudflare",
        "baota": "宝塔面板",
    }
    label = labels.get(key, key)
    config = db.scalar(
        select(SystemPlatformConfiguration).where(
            SystemPlatformConfiguration.platform_key == key
        )
    )
    credential = db.scalar(
        select(SystemCredential).where(
            SystemCredential.platform_key == key,
            SystemCredential.credential_key == credential_key,
        )
    )
    if config is None or not config.enabled or credential is None:
        raise PlatformClientError(f"请先在系统配置中启用并测试 {label}")
    if config.last_test_status != "success":
        raise PlatformClientError(f"请先在系统配置中完成 {label} 连接测试")
    try:
        secret = decrypt_secret(credential.value_ciphertext)
    except ValueError as exc:
        raise PlatformClientError(f"{label} 凭据无法读取，请重新配置") from exc
    return _Platform(secret=secret, settings=dict(config.settings_json or {}))


def _save(
    db: Session,
    item: DomainRecord,
    *,
    status: str,
    stage: str,
    message: str | None,
    state: dict[str, object],
) -> None:
    item.onboarding_status = status
    item.onboarding_stage = stage
    item.onboarding_message = message
    item.onboarding_state_json = dict(state)
    if status == "completed":
        item.onboarding_completed_at = utcnow()
    db.commit()
    db.refresh(item)


def _wait(
    db: Session,
    item: DomainRecord,
    *,
    stage: str,
    message: str,
    state: dict[str, object],
) -> DomainRecord:
    item.last_error = None
    _save(db, item, status="waiting", stage=stage, message=message, state=state)
    return item


def _fail(
    db: Session,
    item: DomainRecord,
    *,
    stage: str,
    message: str,
    state: dict[str, object],
) -> DomainRecord:
    item.last_error = message[:1000]
    item.hosting_status = "failed"
    _save(
        db,
        item,
        status="failed",
        stage=stage,
        message=message[:1000],
        state=state,
    )
    return item


def _nameservers(zone: dict[str, object]) -> list[str]:
    raw = zone.get("name_servers") or zone.get("nameservers") or []
    if not isinstance(raw, list | tuple):
        raw = [raw]
    return [
        value
        for value in (str(item or "").strip().lower().rstrip(".") for item in raw)
        if value
    ]


def continue_domain_onboarding(db: Session, item: DomainRecord) -> DomainRecord:
    """Advance a domain as far as current third-party state safely allows.

    This is deliberately synchronous and user-driven. Every mutation is preceded
    or followed by a read so a later click can recover after an uncertain response.
    """

    state = dict(item.onboarding_state_json or {})
    stage = item.onboarding_stage or "not_started"
    cloudflare: CloudflareClient | None = None
    namesilo: NameSiloClient | None = None
    baota: BaoTaClient | None = None
    try:
        cf_platform = _platform(db, "cloudflare", "api_token")
        account_id = str(cf_platform.settings.get("accountId") or "").strip()
        if not account_id:
            raise PlatformClientError("请先在系统配置中选择 Cloudflare 账户")
        cloudflare = CloudflareClient(
            cf_platform.secret,
            account_id=account_id,
        )

        stage = "cloudflare_zone"
        zone = cloudflare.find_zone(item.hostname)
        if zone is None:
            zone = cloudflare.create_zone(item.hostname)
        zone_id = str(zone.get("id") or "")
        if not zone_id:
            raise PlatformClientError("Cloudflare Zone 缺少 ID")
        nameservers = _nameservers(zone)
        state.update(
            {
                "cloudflareZoneId": zone_id,
                "cloudflareZoneStatus": str(zone.get("status") or "pending"),
                "cloudflareNameservers": nameservers,
            }
        )
        _save(
            db,
            item,
            status="running",
            stage=stage,
            message="Cloudflare Zone 已就绪",
            state=state,
        )

        stage = "registrar_nameservers"
        purchased_with_namesilo = (
            item.acquisition_type == "purchased" and item.registrar_provider == "namesilo"
        )
        if purchased_with_namesilo:
            ns_platform = _platform(db, "namesilo", "api_key")
            namesilo = NameSiloClient(
                ns_platform.secret,
                payment_id=str(ns_platform.settings.get("paymentId") or "") or None,
            )
            if not namesilo.owns_domain(item.hostname):
                raise PlatformClientError("NameSilo 当前账户中未找到该域名")
            if len(nameservers) < 2:
                raise PlatformClientError("Cloudflare 尚未返回域名服务器，请稍后继续")
            info = namesilo.get_domain_info(item.hostname)
            current_ns = {
                str(value).lower().rstrip(".")
                for value in info.get("nameservers", [])
                if str(value).strip()
            }
            if current_ns != set(nameservers):
                namesilo.change_name_servers(item.hostname, nameservers)
                state["registrarNameserversUpdated"] = True
            _save(
                db,
                item,
                status="running",
                stage=stage,
                message="NameSilo 域名服务器已核对",
                state=state,
            )

        zone = cloudflare.find_zone(item.hostname) or zone
        zone_status = str(zone.get("status") or "pending").lower()
        nameservers = _nameservers(zone) or nameservers
        state["cloudflareZoneStatus"] = zone_status
        state["cloudflareNameservers"] = nameservers
        if zone_status != "active":
            if purchased_with_namesilo:
                message = "域名服务器已提交，等待 Cloudflare 激活；稍后点击继续即可"
            else:
                message = "请在域名注册商处改用下列 Cloudflare 域名服务器，生效后点击继续"
            return _wait(
                db,
                item,
                stage=stage,
                message=message,
                state=state,
            )

        stage = "cloudflare_dns"
        settings = get_settings()
        cloudflare.ensure_dns_record(
            zone_id,
            record_type="CNAME",
            name=item.hostname,
            content=settings.promotion_ingress_host,
            proxied=True,
        )
        cloudflare.ensure_dns_record(
            zone_id,
            record_type="TXT",
            name=f"_parloq-verify.{item.hostname}",
            content=f"parloq-verification={item.verification_token}",
        )
        cloudflare.ensure_zone_setting(zone_id, "ssl", "flexible")
        cloudflare.ensure_zone_setting(zone_id, "always_use_https", "on")
        state["cloudflareDnsReady"] = True
        _save(
            db,
            item,
            status="running",
            stage=stage,
            message="Cloudflare DNS 与 HTTPS 设置已就绪",
            state=state,
        )

        stage = "baota_site"
        baota_platform = _platform(db, "baota", "api_key")
        base_url = str(baota_platform.settings.get("baseUrl") or "").strip()
        if not base_url:
            raise PlatformClientError("请先在系统配置中填写宝塔面板地址")
        baota = BaoTaClient(base_url, baota_platform.secret)
        upstream = "http://127.0.0.1:18100"
        expected_path = f"/www/wwwroot/{item.hostname}"
        site = baota.find_site(item.hostname)
        if site is None:
            # Persist the intent first; an uncertain response can then be recovered
            # by reading the site on the next user-triggered continuation.
            state["baotaSiteIntent"] = True
            _save(
                db,
                item,
                status="running",
                stage=stage,
                message="正在创建独立宝塔站点",
                state=state,
            )
            site = baota.create_site(item.hostname, expected_path)
        elif not state.get("baotaSiteIntent"):
            proxy_state = baota.reverse_proxy_state(item.hostname, upstream)
            if proxy_state != "exact":
                raise PlatformClientError(
                    "宝塔已存在同名站点且不属于本接入流程，已停止以避免覆盖"
                )
            state["baotaSiteAdopted"] = True
        site_path = str(site.get("path") or expected_path)
        if state.get("baotaSiteIntent") and site_path.rstrip("/") != expected_path:
            raise PlatformClientError("宝塔同名站点目录与预期不一致，已停止以避免接管")
        baota.ensure_reverse_proxy(item.hostname, upstream)
        state.update(
            {
                "baotaSiteId": str(site.get("id") or ""),
                "baotaSiteReady": True,
            }
        )
        item.hosting_status = "pending"
        _save(
            db,
            item,
            status="running",
            stage=stage,
            message="宝塔独立站点与反向代理已就绪",
            state=state,
        )

        stage = "public_verification"
        item.last_verified_at = utcnow()
        if not settings.domain_verify_mock:
            verify_public_domain(
                item.hostname,
                verification_name=f"_parloq-verify.{item.hostname}",
                verification_value=f"parloq-verification={item.verification_token}",
                cname_target=settings.promotion_ingress_host,
                routing_probe_path=f"/api/domains/public-verification/{item.verification_token}",
            )
        item.registration_status = "active"
        item.dns_status = "verified"
        item.ssl_status = "verified"
        item.hosting_status = "active"
        item.last_error = None
        _save(
            db,
            item,
            status="completed",
            stage="completed",
            message="域名已自动接入并通过公网验证",
            state=state,
        )
        return item
    except DomainVerifyError as exc:
        item.registration_status = "pending"
        item.dns_status = "untested"
        item.ssl_status = "untested"
        item.hosting_status = "pending"
        return _wait(
            db,
            item,
            stage=stage,
            message=f"配置已完成，等待 DNS 或 HTTPS 生效：{str(exc)[:500]}",
            state=state,
        )
    except PlatformClientError as exc:
        if exc.outcome_unknown:
            return _wait(
                db,
                item,
                stage=stage,
                message="外部平台写入结果暂时无法确认；稍后继续时会先核对现状",
                state=state,
            )
        return _fail(
            db,
            item,
            stage=stage,
            message=str(exc),
            state=state,
        )
    finally:
        for client in (cloudflare, namesilo, baota):
            if client is not None:
                client.close()
