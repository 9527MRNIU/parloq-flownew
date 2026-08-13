from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_database
from app.routers import (
    account_statistics,
    auth,
    bitly_accounts,
    direct_short_links,
    groups,
    domains,
    hyperlink,
    ip_proxies,
    meta_pixels,
    personal_accounts,
    promotion,
    protocol_nodes,
    system,
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

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(users.router)
app.include_router(bitly_accounts.router)
app.include_router(direct_short_links.router)
app.include_router(meta_pixels.router)
app.include_router(ip_proxies.router)
app.include_router(personal_accounts.router)
app.include_router(personal_accounts.group_router)
app.include_router(account_statistics.router)
app.include_router(protocol_nodes.router)
app.include_router(domains.router)
app.include_router(domains.order_router)
app.include_router(promotion.router)
app.include_router(system.router)
app.include_router(hyperlink.router)
app.include_router(wa_gateway_events.router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
