from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from app.config import get_settings
from app.models import ProxyEndpoint
from app.security import decrypt_secret, utcnow
from app.services.wa_gateway import GatewayError, WaGatewayClient


class ProxyHealthError(Exception):
    pass


@dataclass(frozen=True)
class ProxyProbeResult:
    healthy: bool
    latency_ms: int | None = None
    reason_category: str = "proxy_ok"
    error: str | None = None
    country_code: str | None = None


@dataclass(frozen=True)
class ProxyHealthPolicy:
    failure_threshold: int = 2
    cooldown_seconds: int = 900


@dataclass(frozen=True)
class ProxyHealthTransition:
    entered_cooldown: bool
    recovered: bool


HARD_FAILURE_REASONS = {
    "proxy_authentication_failed",
    "proxy_configuration_invalid",
}


def proxy_connection_url(proxy: ProxyEndpoint) -> str:
    username = (
        decrypt_secret(proxy.username_ciphertext)
        if proxy.username_ciphertext
        else ""
    )
    password = (
        decrypt_secret(proxy.password_ciphertext)
        if proxy.password_ciphertext
        else ""
    )
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return f"{proxy.protocol}://{auth}{proxy.host}:{proxy.port}"


def proxy_fingerprint(proxy: ProxyEndpoint) -> str:
    return hashlib.sha256(proxy_connection_url(proxy).encode()).hexdigest()


def proxy_is_quarantined(proxy: ProxyEndpoint) -> bool:
    now = utcnow()
    if proxy.cooldown_until is not None:
        cooldown_until = proxy.cooldown_until
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=now.tzinfo)
        return cooldown_until > now
    return proxy.health_status == "unhealthy"


def validate_public_proxy_endpoint(host: str, port: int) -> None:
    """Resolve a proxy host and reject private/internal destinations.

    The actual protocol and credential check runs inside the WhatsApp gateway;
    this guard only prevents the control plane from turning that fixed-target
    probe into an internal-network tunnel.
    """

    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProxyHealthError("代理主机无法解析") from exc
    found_public = False
    for address in addresses:
        raw_ip = str(address[4][0]).split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if not parsed.is_global:
            raise ProxyHealthError("安全策略禁止探测内网、回环或保留地址")
        found_public = True
    if not found_public:
        raise ProxyHealthError("代理主机没有可用的公网地址")


def probe_proxy(proxy: ProxyEndpoint) -> ProxyProbeResult:
    if get_settings().ip_proxy_mock:
        return ProxyProbeResult(healthy=True, latency_ms=0)
    validate_public_proxy_endpoint(proxy.host, proxy.port)
    try:
        result = WaGatewayClient().test_proxy(proxy_connection_url(proxy))
    except GatewayError as exc:
        raise ProxyHealthError(str(exc)) from None
    healthy = bool(result.get("healthy"))
    latency_value = result.get("latencyMs")
    latency_ms = (
        max(0, int(latency_value))
        if isinstance(latency_value, (int, float))
        else None
    )
    reason = str(result.get("reasonCategory") or "proxy_probe_failed")[:64]
    error = str(result.get("error") or "代理无法访问 WhatsApp Web")[:2000]
    raw_country = result.get("countryCode")
    normalized_country = (
        raw_country.strip().upper() if isinstance(raw_country, str) else ""
    )
    country_code = (
        normalized_country
        if len(normalized_country) == 2
        and normalized_country.isascii()
        and normalized_country.isalpha()
        else None
    )
    return ProxyProbeResult(
        healthy=healthy,
        latency_ms=latency_ms,
        reason_category=reason,
        error=None if healthy else error,
        country_code=country_code,
    )


def apply_proxy_health_result(
    proxy: ProxyEndpoint,
    result: ProxyProbeResult,
    *,
    source: str,
    policy: ProxyHealthPolicy,
    direct_probe: bool = False,
) -> ProxyHealthTransition:
    now = utcnow()
    was_healthy = proxy.health_status == "healthy"
    was_quarantined = proxy_is_quarantined(proxy)
    proxy.last_checked_at = now
    proxy.last_check_source = source[:24]
    proxy.latency_ms = result.latency_ms
    if not proxy.country_code and result.country_code:
        proxy.country_code = result.country_code
    if result.healthy:
        proxy.health_status = "healthy"
        proxy.consecutive_failures = 0
        proxy.cooldown_until = None
        proxy.last_success_at = now
        proxy.last_error = None
        return ProxyHealthTransition(
            entered_cooldown=False,
            recovered=not was_healthy,
        )

    proxy.last_failure_at = now
    proxy.last_error = (result.error or "代理连接失败")[:2000]
    next_failures = int(proxy.consecutive_failures or 0) + 1
    if direct_probe:
        next_failures = max(next_failures, policy.failure_threshold)
    proxy.consecutive_failures = next_failures
    hard_failure = result.reason_category in HARD_FAILURE_REASONS
    threshold_reached = next_failures >= policy.failure_threshold
    entered_cooldown = hard_failure or threshold_reached
    if entered_cooldown:
        proxy.health_status = "unhealthy"
        # Authentication/configuration failures cannot heal by waiting. They
        # stay quarantined until the proxy is edited or a manual probe passes.
        proxy.cooldown_until = (
            None
            if hard_failure
            else now + timedelta(seconds=policy.cooldown_seconds)
        )
    return ProxyHealthTransition(
        entered_cooldown=entered_cooldown and not was_quarantined,
        recovered=False,
    )
