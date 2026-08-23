from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.middleware.public_pairing_cors import PublicPairingCorsMiddleware

from app.config import get_settings
from app.database import engine, init_database
from app.task_queue import redis_client
from app.worker_health import worker_status
from app.routers import (
    account_statistics,
    auth,
    bitly_accounts,
    direct_short_links,
    developer_docs,
    groups,
    domains,
    hyperlink,
    ip_proxies,
    materials,
    meta_pixels,
    personal_accounts,
    promotion,
    promotion_integrations,
    promotion_monitoring,
    promotion_policy,
    protocol_nodes,
    system,
    system_configuration,
    users,
    wa_gateway_events,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_database()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# This middleware is intentionally added after CORSMiddleware so it is the
# outer, route-scoped exception for opaque public-template origins. It must not
# widen the management API's global CORS allowlist.
app.add_middleware(PublicPairingCorsMiddleware)

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(users.router)
app.include_router(bitly_accounts.router)
app.include_router(direct_short_links.router)
app.include_router(developer_docs.router)
app.include_router(meta_pixels.router)
app.include_router(materials.router)
app.include_router(materials.legacy_router)
app.include_router(materials.internal_router)
app.include_router(ip_proxies.router)
app.include_router(personal_accounts.router)
app.include_router(personal_accounts.group_router)
app.include_router(account_statistics.router)
app.include_router(protocol_nodes.router)
app.include_router(protocol_nodes.pool_router)
app.include_router(domains.router)
app.include_router(domains.order_router)
app.include_router(promotion.router)
app.include_router(promotion_integrations.router)
app.include_router(promotion_integrations.public_router)
app.include_router(promotion_monitoring.router)
app.include_router(promotion_policy.router)
app.include_router(system.router)
app.include_router(system_configuration.router)
app.include_router(hyperlink.router)
app.include_router(wa_gateway_events.router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    worker: dict = {"healthy": False, "heartbeatAgeSeconds": None}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        client = redis_client()
        client.ping()
        checks["redis"] = "ok"
        worker = worker_status(client)
    except Exception:
        checks["redis"] = "unavailable"
    ready = all(value == "ok" for value in checks.values()) and bool(
        worker.get("healthy")
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "worker": worker,
        },
    )
