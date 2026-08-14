# Parloq Flow Agent Instructions

These repository-level instructions persist across Codex tasks. Follow them
together with the current user request.

## Protect Existing Work

- The working tree may contain intentional changes. Inspect `git status` and
  the relevant diff before editing, committing, building, or deploying.
- Never reset, discard, overwrite, or silently include unrelated work.
- Production releases must identify the exact Git commit used for every image.

## Local Development

- Local development uses `docker-compose.yml` and is intentionally separate
  from production.
- Run API tests, the web production build, Baileys gateway tests/build, and a
  resolved Compose validation for changes that affect deployment.
- Do not enable the real Baileys engine locally except for an explicit test
  with a disposable WhatsApp account and a fixed proxy.

## ID Policy

- All Parloq entity primary and foreign keys use signed `BIGINT` Snowflake IDs.
- The custom Snowflake epoch is `2026-08-01 00:00:00 UTC`, with a
  41-bit millisecond timestamp, 10-bit writer node, and 12-bit sequence.
- Public business IDs retain their resource prefix and use the Snowflake value,
  for example `ptpl_<snowflake>`, `htsk_<snowflake>`, and `msg_<snowflake>`.
- Serialize Snowflake values as strings at HTTP/JavaScript boundaries. Never
  coerce them to a JavaScript `Number`.
- Every concurrent API, worker, gateway, migration, or future writer process
  needs a distinct configured node ID. Follow `docs/id-conventions.md`.
- Cryptographic tokens, client idempotency keys, protocol key IDs, and IDs
  assigned by third-party providers are not Parloq entity IDs.

## Production Environment

- Production host: `216.106.185.81`.
- BaoTa panel: `https://bt2.felixweb.top:10049` (version 11.8.1 at the
  2026-08-14 handoff).
- BaoTa HTTP APIs are the only production write control plane. Do not use SSH,
  SCP, direct Nginx edits, direct Compose commands, or direct SQLite changes to
  mutate production.
- The local untracked `.env.baota.local` records the connection. The deployment
  client opens an SSH port-forward to BaoTa's loopback listener and sends every
  mutation through the authenticated BaoTa API. SSH is transport/read-only
  diagnostics only; it does not authorize remote write commands.
- Public management origin: `https://center.parloq.com`.
- Promotion landing pages use customer-owned domains. They are not assigned a
  Parloq subdomain by default.
- BaoTa Compose project: `parloq-flow`.
- BaoTa Compose record ID: `1` at the 2026-08-14 handoff.
- Compose directory:
  `/www/server/panel/data/compose/parloq-flow`.
- Compose file:
  `/www/server/panel/data/compose/parloq-flow/docker-compose.yaml`.
- Production environment file:
  `/www/server/panel/data/compose/parloq-flow/.env`.
- Persistent data root: `/data/parloq-flow`.
- Host-only application port: `127.0.0.1:18100`.
- Nginx vhost:
  `/www/server/panel/vhost/nginx/center.parloq.com.conf`.
- BaoTa website record: `center.parloq.com`, ID `38` at the 2026-08-14
  handoff. Its BaoTa reverse-proxy record is `parloq-flow` targeting
  `http://127.0.0.1:18100`.
- Existing WABA production is a different system. Never alter its `waba`
  Compose project, `/www/server/panel/data/compose/waba`, `/data/waba`, images,
  containers, ports `8000/8002`, or `app.parloq.com` while operating this repo.

Begin production work read-only. Confirm container labels, image revisions,
health, restart counts, disk space, target paths, listening ports, Nginx config,
and DNS before changing anything. Never print `.env` values, database passwords,
tokens, proxy credentials, WhatsApp credentials, Signal keys, or session JSON.

## Production Release Policy

The repository owner's standing preference is to build `linux/amd64` images on
the local Mac and upload them directly to production. Do not wait for a cloud
registry build unless the user explicitly changes this policy.

When the user authorizes a production release:

1. Require a clean working tree, confirm `main` is pushed, and record the exact
   commit SHA. Run `python3 deploy/baota_api.py status` before building.
2. Build immutable images locally with `deploy/build-production-images.sh`:
   `parloq-flow-api-local:<sha>`, `parloq-flow-web-local:<sha>`, and
   `parloq-flow-wa-gateway-local:<sha>` for `linux/amd64`.
3. Export only those images as a tar archive and upload it with BaoTa's chunked
   File API. The local script must not use SCP.
4. Start a temporary, audited BaoTa task that verifies SHA-256, loads the
   images, backs up `.env`, and changes only the three image variables. The
   task must publish a status file that the client polls before cleanup.
5. Validate Compose inside that BaoTa task.
6. Run `migrate` with the `migration` profile and require a zero exit code
   before recreating `api`, `api-worker`, `wa-gateway`, and `web`. The profile
   prevents the successful one-shot container from making BaoTa show the whole
   stack as stopped.
7. Never recreate, delete, or clear PostgreSQL/Redis data as part of a release.
   Never use `docker compose down -v`, and never delete `/data/parloq-flow`.
8. Verify image revisions, migration status, health, restart counts,
   `http://127.0.0.1:18100/healthz`, public HTTPS when DNS is ready, and recent
   error logs.
9. Keep prior image tags and the `.env` backup until verification passes. On
   failure, restore the previous image variables and recreate only application
   services; report the failure and rollback result.
10. Remove local and remote transfer archives only after a successful release;
    retain the `.env` backup.

The checked-in Compose file is the desired managed Compose configuration. The
Nginx file contains reference fragments only. Never install it over BaoTa's
generated vhost. Site, proxy, certificate, and marked custom fragments are
reconciled through BaoTa APIs.

## Domains and Nginx

- `center.parloq.com` is a separate BaoTa website with an exact reverse-proxy
  record pointing to `127.0.0.1:18100`; it must not be added to the old
  application's upstream.
- The existing wildcard `parloq.com` vhost belongs to the old system. An exact
  `center.parloq.com` block takes precedence and preserves isolation.
- The origin follows the existing Cloudflare-only ingress policy. DNS changes
  happen in Cloudflare and must direct `center.parloq.com` to this production
  origin before public verification.
- Each customer landing-page domain needs DNS pointing at the ingress and an
  explicit BaoTa website/proxy/certificate. Do not install a global default
  vhost that could capture unrelated sites on the shared server.
- `PROMOTION_INGRESS_HOST=center.parloq.com` is the canonical DNS verification
  target; it does not mean customer landing pages must use the system domain.

Detailed bootstrap, release, rollback, DNS, and customer-domain instructions
are in `docs/production-deployment.md`.
