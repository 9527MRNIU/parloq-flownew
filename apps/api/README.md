# Parloq Flow API

FastAPI control plane for Parloq Flow. It covers tenant-owned personal
accounts, promotion channels/templates, direct Bitly links, domains, Meta
pixel metadata, and hyperlink marketing. It does not store WhatsApp message
bodies, replies, chats, or media.

## Local run

```bash
python -m pip install -e '.[dev]'
BITLY_MOCK=true WA_GATEWAY_MOCK=true TASK_QUEUE_MOCK=true \
  DATABASE_URL=sqlite+pysqlite:///./dev.db uvicorn app.main:app --reload
```

The Docker development environment uses PostgreSQL. On startup the service
creates missing tables and idempotently seeds `admin/admin`. Alembic contains
the equivalent initial schema and admin seed for managed migrations.

Authentication accepts either the HttpOnly `parloq_session` cookie set by
`POST /api/auth/login`, or `Authorization: Bearer <token>`. Browser clients
should prefer the cookie and send requests with `credentials: 'include'`.

`BITLY_MOCK=true` seeds an enabled mock provider account and keeps all Bitly
operations local. Real mode sends direct Bitlink requests to Bitly v4 and
requires a provider Access Token. Provider and Meta CAPI tokens are encrypted
at rest and API responses only include a masked suffix.

IP isolation v1 is exposed through `/api/ip-proxies` and
`/api/ip-proxy-bindings`. Proxy usernames and passwords are both encrypted and
only masked suffixes are returned. `IP_PROXY_MOCK=true` makes the health action
deterministically healthy for local UI development. In real mode the v1 health
action only checks TCP reachability after rejecting private, loopback,
link-local, and reserved destinations; it never probes an internal URL or sends
stored credentials.

## WhatsApp gateway and task worker

Normal Docker development uses the Baileys gateway HTTP boundary with its
deterministic `WA_ENGINE=mock`; `WA_GATEWAY_MOCK` is only for isolated Python
tests. Configure `WA_GATEWAY_BASE_URL`, `WA_GATEWAY_API_TOKEN`, and the shared
`WA_GATEWAY_WEBHOOK_SECRET`. Gateway status callbacks are verified over the
exact request bytes before parsing and advance only `queued`, `sent`,
`delivered`, or `failed` timestamps.

Hyperlink task start is asynchronous: the API durably creates idempotent
delivery rows, enqueues the task in Redis, and returns HTTP 202. Run the worker
as a separate process:

```bash
python -m app.task_worker
```

The worker uses a shared HTTP keepalive pool, bounded batch/concurrency values,
checks pause/cancel between batches, and renders message text only in memory.

## Business API boundaries

- Promotion templates and channels are `/api/promotion/templates` and
  `/api/promotion/channels`; ZIP imports require `index.html`, while manifest,
  assets, and bundled locale JSON are optional.
- GitHub-backed templates and integrations are listed from the configured
  private repository's `artifacts/catalog.json`; source directories are read
  directly and imported through the same validators without requiring release
  ZIP artifacts.
- Channel statistics and daily trends are
  `/api/promotion/data-center/channels` and
  `/api/promotion/data-center/trends`. Facebook daily spend, other cost,
  impressions, and clicks remain editable at `/api/promotion/ad-metrics`.
- Domain purchase uses the local registrar fixture when `DOMAIN_REGISTRAR_MOCK`
  is enabled. In production it uses the enabled NameSilo configuration saved
  under System Configuration, including the optional Payment ID. Create an
  expiring quote at `/api/domain-orders/quote`, create the order with its
  `quoteId`, then explicitly confirm the purchase through `/provision`. An
  uncertain provider response moves the order to `unknown`; only `/reconcile`
  may advance it, so purchase is never blindly retried. Connected domains
  expose CNAME/TXT instructions and are not selectable by a channel until
  hostname, TLS, and hosting are active. The authenticated
  `POST /api/domains/{id}/onboarding/continue` action advances the lightweight
  NameSilo → Cloudflare → BaoTa → public-verification workflow. It pauses with
  an operator-facing status when DNS or another external change is still
  pending; it does not schedule background retries.
- Roles and the complete single-system menu tree are persisted under
  `/api/system/roles` and `/api/system/menus`; `/api/system/menus/me` returns
  the current user's permitted tree.
- `/api/hyperlink/market-insights` is the separate source-account-country ×
  target-country sending/delivery/restriction view.
- Tenant-owned resources are filtered by `created_by`; administrators can see
  all tenants. Proxy endpoints remain an administrator-managed global pool and
  operators only see masked proxies bound to their own personal accounts.

## Verification

```bash
python -m pytest
alembic upgrade head
```
