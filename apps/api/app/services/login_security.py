from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx
from redis import Redis

from app.config import Settings, get_settings


logger = logging.getLogger("parloq.auth")


class LoginSecurityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LoginSecurityState:
    turnstile_required: bool
    locked: bool
    retry_after_seconds: int


def _identity_digest(kind: str, value: str, settings: Settings) -> str:
    return hmac.new(
        settings.app_secret_key.encode("utf-8"),
        f"{kind}:{value.strip().lower()}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _keys(username: str, source_ip: str, settings: Settings) -> dict[str, str]:
    user = _identity_digest("user", username, settings)
    source = _identity_digest("ip", source_ip, settings)
    return {
        "user_failures": f"parloq:login:failures:user:{user}",
        "ip_failures": f"parloq:login:failures:ip:{source}",
        "user_lock": f"parloq:login:lock:user:{user}",
        "ip_lock": f"parloq:login:lock:ip:{source}",
    }


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def state(username: str, source_ip: str) -> LoginSecurityState:
    settings = get_settings()
    if not settings.login_security_enabled:
        return LoginSecurityState(False, False, 0)
    keys = _keys(username, source_ip, settings)
    try:
        client = _redis(settings)
        values = client.mget(
            keys["user_failures"],
            keys["ip_failures"],
            keys["user_lock"],
            keys["ip_lock"],
        )
        user_failures = int(values[0] or 0)
        ip_failures = int(values[1] or 0)
        locked = bool(values[2] or values[3])
        retry_after = max(
            client.ttl(keys["user_lock"]),
            client.ttl(keys["ip_lock"]),
            0,
        )
    except Exception as exc:
        raise LoginSecurityUnavailable("登录安全状态不可用") from exc
    return LoginSecurityState(
        turnstile_required=settings.turnstile_enabled
        and (user_failures > 0 or ip_failures > 0),
        locked=locked,
        retry_after_seconds=retry_after,
    )


def record_failure(username: str, source_ip: str) -> LoginSecurityState:
    settings = get_settings()
    if not settings.login_security_enabled:
        return LoginSecurityState(False, False, 0)
    keys = _keys(username, source_ip, settings)
    try:
        client = _redis(settings)
        pipe = client.pipeline(transaction=True)
        pipe.incr(keys["user_failures"])
        pipe.expire(keys["user_failures"], settings.login_lock_window_seconds)
        pipe.incr(keys["ip_failures"])
        pipe.expire(keys["ip_failures"], settings.login_lock_window_seconds)
        result = pipe.execute()
        user_failures = int(result[0])
        ip_failures = int(result[2])
        lock_pipe = client.pipeline(transaction=True)
        if user_failures >= settings.login_user_failure_limit:
            lock_pipe.set(keys["user_lock"], "1", ex=settings.login_lock_seconds)
        if ip_failures >= settings.login_ip_failure_limit:
            lock_pipe.set(keys["ip_lock"], "1", ex=settings.login_lock_seconds)
        lock_pipe.execute()
    except Exception as exc:
        raise LoginSecurityUnavailable("登录失败计数不可用") from exc
    logger.warning(
        "login_failed",
        extra={
            "username_hash": _identity_digest("audit-user", username, settings)[:16],
            "source_ip_hash": _identity_digest("audit-ip", source_ip, settings)[:16],
            "user_failure_count": user_failures,
            "ip_failure_count": ip_failures,
        },
    )
    return LoginSecurityState(
        turnstile_required=settings.turnstile_enabled,
        locked=(
            user_failures >= settings.login_user_failure_limit
            or ip_failures >= settings.login_ip_failure_limit
        ),
        retry_after_seconds=settings.login_lock_seconds,
    )


def clear_user_failures(username: str, source_ip: str) -> None:
    settings = get_settings()
    if not settings.login_security_enabled:
        return
    keys = _keys(username, source_ip, settings)
    try:
        _redis(settings).delete(keys["user_failures"], keys["user_lock"])
    except Exception as exc:
        raise LoginSecurityUnavailable("登录安全状态不可用") from exc


def verify_turnstile(token: str | None, source_ip: str) -> bool:
    settings = get_settings()
    if not settings.turnstile_enabled:
        return True
    if not token:
        return False
    try:
        response = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.turnstile_secret_key,
                "response": token,
                "remoteip": source_ip,
            },
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        logger.warning("turnstile_verification_failed")
        return False
