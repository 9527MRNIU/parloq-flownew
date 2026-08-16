from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    app_secret_key: str
    auth_cookie_name: str
    auth_session_hours: int
    cookie_secure: bool
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
        if errors:
            raise RuntimeError("生产配置不安全：" + "；".join(errors))
    return settings
