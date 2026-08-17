from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(os.getenv(name, str(default))), maximum))


def _encryption_keys_env() -> tuple[tuple[str, str], ...]:
    raw = os.getenv("DATA_ENCRYPTION_KEYS", "").strip()
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DATA_ENCRYPTION_KEYS 必须是 JSON 对象") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError("DATA_ENCRYPTION_KEYS 必须是非空 JSON 对象")
    result: list[tuple[str, str]] = []
    for key_id, key_value in parsed.items():
        if not isinstance(key_id, str) or not key_id or ":" in key_id:
            raise RuntimeError("DATA_ENCRYPTION_KEYS 包含无效的密钥 ID")
        if not isinstance(key_value, str):
            raise RuntimeError("DATA_ENCRYPTION_KEYS 的密钥必须是字符串")
        try:
            decoded = base64.urlsafe_b64decode(key_value.encode("ascii"))
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise RuntimeError("DATA_ENCRYPTION_KEYS 包含无效的 Fernet 密钥") from exc
        if len(decoded) != 32:
            raise RuntimeError("DATA_ENCRYPTION_KEYS 的 Fernet 密钥必须解码为 32 字节")
        result.append((key_id, key_value))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    app_secret_key: str
    auth_cookie_name: str
    auth_session_hours: int
    cookie_secure: bool
    login_security_enabled: bool
    login_lock_window_seconds: int
    login_lock_seconds: int
    login_user_failure_limit: int
    login_ip_failure_limit: int
    turnstile_enabled: bool
    turnstile_site_key: str
    turnstile_secret_key: str
    data_encryption_active_key_id: str
    data_encryption_keys: tuple[tuple[str, str], ...]
    auto_create_tables: bool
    seed_admin_username: str
    seed_admin_password: str
    bitly_mock: bool
    bitly_base_url: str
    ip_proxy_mock: bool
    wa_gateway_url: str
    wa_gateway_mock: bool
    wa_gateway_api_token: str
    wa_gateway_webhook_secret: str
    redis_url: str
    task_queue_mock: bool
    pairing_rate_limit_mock: bool
    task_worker_max_concurrency: int
    domain_verify_mock: bool
    domain_registrar_mock: bool
    promotion_ingress_host: str
    promotion_success_webhook_secret: str
    meta_capi_mock: bool
    meta_capi_base_url: str
    meta_capi_api_version: str
    meta_capi_max_attempts: int
    meta_capi_batch_size: int
    system_host_proc_path: str
    system_host_disk_path: str
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    origins = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if item.strip()
    )
    settings = Settings(
        app_name="Parloq Flow API",
        environment=os.getenv("APP_ENV", "development"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://parloq:parloq@postgres:5432/parloq",
        ),
        app_secret_key=os.getenv("APP_SECRET_KEY", "parloq-dev-secret-change-me"),
        auth_cookie_name=os.getenv("AUTH_COOKIE_NAME", "parloq_session"),
        auth_session_hours=max(int(os.getenv("AUTH_SESSION_HOURS", "24")), 1),
        cookie_secure=_bool_env("COOKIE_SECURE", False),
        login_security_enabled=_bool_env(
            "LOGIN_SECURITY_ENABLED",
            os.getenv("APP_ENV", "development").lower() in {"production", "prod"},
        ),
        login_lock_window_seconds=_bounded_int_env(
            "LOGIN_LOCK_WINDOW_SECONDS", 900, 60, 86400
        ),
        login_lock_seconds=_bounded_int_env("LOGIN_LOCK_SECONDS", 600, 60, 86400),
        login_user_failure_limit=_bounded_int_env(
            "LOGIN_USER_FAILURE_LIMIT", 5, 2, 100
        ),
        login_ip_failure_limit=_bounded_int_env(
            "LOGIN_IP_FAILURE_LIMIT", 20, 2, 1000
        ),
        turnstile_enabled=_bool_env("TURNSTILE_ENABLED", False),
        turnstile_site_key=os.getenv("TURNSTILE_SITE_KEY", "").strip(),
        turnstile_secret_key=os.getenv("TURNSTILE_SECRET_KEY", "").strip(),
        data_encryption_active_key_id=os.getenv(
            "DATA_ENCRYPTION_ACTIVE_KEY_ID", ""
        ).strip(),
        data_encryption_keys=_encryption_keys_env(),
        auto_create_tables=_bool_env("AUTO_CREATE_TABLES", True),
        seed_admin_username=os.getenv("SEED_ADMIN_USERNAME", "admin"),
        seed_admin_password=os.getenv("SEED_ADMIN_PASSWORD", "admin"),
        bitly_mock=_bool_env("BITLY_MOCK", False),
        bitly_base_url=os.getenv("BITLY_BASE_URL", "https://api-ssl.bitly.com").rstrip("/"),
        ip_proxy_mock=_bool_env("IP_PROXY_MOCK", _bool_env("BITLY_MOCK", False)),
        wa_gateway_url=os.getenv(
            "WA_GATEWAY_URL",
            os.getenv("WA_GATEWAY_BASE_URL", "http://wa-gateway:8010"),
        ).rstrip("/"),
        # Local development uses the Baileys gateway's deterministic mock engine.  This
        # in-process mock is retained only for isolated API unit tests.
        wa_gateway_mock=_bool_env("WA_GATEWAY_MOCK", False),
        wa_gateway_api_token=os.getenv("WA_GATEWAY_API_TOKEN", ""),
        wa_gateway_webhook_secret=os.getenv("WA_GATEWAY_WEBHOOK_SECRET", ""),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        task_queue_mock=_bool_env("TASK_QUEUE_MOCK", False),
        pairing_rate_limit_mock=_bool_env("PAIRING_RATE_LIMIT_MOCK", False),
        task_worker_max_concurrency=max(
            1, min(int(os.getenv("TASK_WORKER_MAX_CONCURRENCY", "200")), 1000)
        ),
        domain_verify_mock=_bool_env(
            "DOMAIN_VERIFY_MOCK", os.getenv("APP_ENV", "development") == "development"
        ),
        domain_registrar_mock=_bool_env(
            "DOMAIN_REGISTRAR_MOCK", os.getenv("APP_ENV", "development") == "development"
        ),
        promotion_ingress_host=os.getenv(
            "PROMOTION_INGRESS_HOST", "promotion.localhost"
        ).strip().lower().rstrip("."),
        promotion_success_webhook_secret=os.getenv(
            "PROMOTION_SUCCESS_WEBHOOK_SECRET", ""
        ),
        meta_capi_mock=_bool_env(
            "META_CAPI_MOCK",
            os.getenv("APP_ENV", "development").lower() == "development",
        ),
        meta_capi_base_url=os.getenv(
            "META_CAPI_BASE_URL", "https://graph.facebook.com"
        ).rstrip("/"),
        meta_capi_api_version=os.getenv(
            "META_CAPI_API_VERSION", "v23.0"
        ).strip(),
        meta_capi_max_attempts=max(
            1, min(int(os.getenv("META_CAPI_MAX_ATTEMPTS", "5")), 20)
        ),
        meta_capi_batch_size=max(
            1, min(int(os.getenv("META_CAPI_BATCH_SIZE", "50")), 500)
        ),
        system_host_proc_path=os.getenv("SYSTEM_HOST_PROC_PATH", "").strip(),
        system_host_disk_path=os.getenv("SYSTEM_HOST_DISK_PATH", "").strip(),
        cors_origins=origins,
    )
    key_ids = {key_id for key_id, _ in settings.data_encryption_keys}
    if (
        settings.data_encryption_active_key_id
        and settings.data_encryption_active_key_id not in key_ids
    ):
        raise RuntimeError(
            "DATA_ENCRYPTION_ACTIVE_KEY_ID 未出现在 DATA_ENCRYPTION_KEYS 中"
        )
    if settings.environment.lower() in {"production", "prod"}:
        errors: list[str] = []
        if len(settings.app_secret_key) < 32 or settings.app_secret_key in {
            "parloq-dev-secret-change-me",
            "local-only-change-before-shared-environment",
        }:
            errors.append("APP_SECRET_KEY 必须使用至少 32 位的生产密钥")
        if (
            len(settings.promotion_success_webhook_secret) < 32
            or settings.promotion_success_webhook_secret.startswith("local-")
        ):
            errors.append("PROMOTION_SUCCESS_WEBHOOK_SECRET 必须配置独立生产密钥")
        if settings.promotion_ingress_host in {"promotion.localhost", "localhost"}:
            errors.append("PROMOTION_INGRESS_HOST 必须配置生产入口域名")
        if not settings.cookie_secure:
            errors.append("COOKIE_SECURE 在生产环境必须为 true")
        if settings.auto_create_tables:
            errors.append("AUTO_CREATE_TABLES 在生产环境必须为 false")
        if (
            settings.seed_admin_password == "admin"
            or len(settings.seed_admin_password) < 12
        ):
            errors.append("SEED_ADMIN_PASSWORD 必须使用至少 12 位的非默认密码")
        if any(
            (
                settings.bitly_mock,
                settings.ip_proxy_mock,
                settings.wa_gateway_mock,
                settings.task_queue_mock,
                settings.pairing_rate_limit_mock,
                settings.domain_verify_mock,
                settings.domain_registrar_mock,
                settings.meta_capi_mock,
            )
        ):
            errors.append("生产环境不得启用 Mock 服务")
        if len(settings.wa_gateway_api_token) < 32:
            errors.append("WA_GATEWAY_API_TOKEN 必须使用至少 32 位的生产令牌")
        if len(settings.wa_gateway_webhook_secret) < 32:
            errors.append("WA_GATEWAY_WEBHOOK_SECRET 必须使用至少 32 位的生产密钥")
        if not settings.login_security_enabled:
            errors.append("LOGIN_SECURITY_ENABLED 在生产环境必须为 true")
        if not settings.turnstile_enabled:
            errors.append("TURNSTILE_ENABLED 在生产环境必须为 true")
        if settings.turnstile_enabled and (
            len(settings.turnstile_site_key) < 10
            or len(settings.turnstile_secret_key) < 20
            or settings.turnstile_site_key.startswith("replace-")
            or settings.turnstile_secret_key.startswith("replace-")
        ):
            errors.append("Turnstile 已启用但 Site Key 或 Secret Key 未配置")
        if not settings.data_encryption_active_key_id or not settings.data_encryption_keys:
            errors.append("生产环境必须配置独立的 DATA_ENCRYPTION_KEYS 活跃密钥")
        if not settings.cors_origins or any(
            not origin.startswith("https://") or "localhost" in origin
            for origin in settings.cors_origins
        ):
            errors.append("生产 CORS_ORIGINS 只能包含 HTTPS 生产域名")
        if errors:
            raise RuntimeError("生产配置不安全：" + "；".join(errors))
    return settings
