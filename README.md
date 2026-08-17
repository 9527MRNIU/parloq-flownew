# Parloq Flow

Parloq Flow is a new outbound marketing console. It intentionally keeps the
visual language and frontend structure of the earlier console without carrying
over unrelated legacy product features.

The development system runs entirely through local Docker Compose. Production
uses a separate, isolated Compose project with locally built immutable images;
see [docs/production-deployment.md](docs/production-deployment.md).

## Local development

Requirements: Docker Desktop with Docker Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open the console at <http://localhost:5173> and sign in with:

- username: `admin`
- password: `admin`

Local services:

| Service | URL or address |
| --- | --- |
| Web console | <http://localhost:5173> |
| API | <http://localhost:8000> |
| API health | <http://localhost:8000/healthz> |
| API readiness | <http://localhost:8000/readyz> |
| WhatsApp gateway health | <http://localhost:8010/healthz> |
| WhatsApp gateway readiness | <http://localhost:8010/readyz> |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

Stop the stack with `docker compose down`. Data in PostgreSQL is preserved in a
named Docker volume. Use `docker compose down -v` only when you deliberately
want to delete all local database data.

## Useful commands

```bash
# Follow the application services
docker compose logs -f web api api-worker wa-gateway

# Build and test the Baileys gateway outside Docker
cd services/wa-gateway-baileys
npm ci
npm test
npm run build

# Validate the resolved Compose model
docker compose --env-file .env.example config --quiet
```

The WhatsApp gateway boots with a deterministic mock engine so the control
plane can be developed without pairing a real phone. Baileys is the only real
protocol adapter and stores credentials plus the Signal key store in
PostgreSQL, with fixed per-account proxies and signed status callbacks. Keep
local Docker on `WA_ENGINE=mock` unless testing with a disposable real WhatsApp
account.

For production, `APP_ENV=production` enables a fail-fast configuration check.
Set independent non-development values for `APP_SECRET_KEY` and
`PROMOTION_SUCCESS_WEBHOOK_SECRET`, and point `PROMOTION_INGRESS_HOST` at the
shared promotion ingress before starting the API. Domain verification and
registrar mocks should also be disabled until their production adapters are
configured.

Gateway control endpoints require the bearer token from
`WA_GATEWAY_API_TOKEN`. See
[services/wa-gateway-baileys/README.md](services/wa-gateway-baileys/README.md) for REST examples,
the disconnect/logout distinction and real pairing steps.

Entity IDs and writer-node allocation follow
[docs/id-conventions.md](docs/id-conventions.md).

## Promotion template example

`examples/promotion-template-demo.zip` is a ready-to-import promotion template.
It contains a responsive phone collection and Baileys pairing page, nine bundled
locales and the standard manifest/runtime integration. Import it in
**推广 → 模板管理**, bind it to a domain in **推广 → 渠道管理**, then open the
channel render URL to exercise the full page-view, dwell-time, phone-lead,
pairing-code and verified-account attribution flow.

See [docs/architecture.md](docs/architecture.md) for system boundaries and
capacity assumptions.

Template authors should follow the versioned
[promotion template specification](docs/promotion-template-spec-v1.md). The
[peer landing-page review](docs/peer-landing-page-review-2026-08.md) records
which public-page patterns we adopted and which ones we deliberately avoided.
