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

## Production Environment

- Production host: `216.106.185.81`.
- SSH uses the local machine's existing key authentication:
  `ssh -o BatchMode=yes root@216.106.185.81`.
- Public management origin: `https://center.parloq.com`.
- Promotion landing pages use customer-owned domains. They are not assigned a
  Parloq subdomain by default.
- BaoTa Compose project: `parloq-flow`.
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
   commit SHA.
2. Build immutable images locally with `deploy/build-production-images.sh`:
   `parloq-flow-api-local:<sha>`, `parloq-flow-web-local:<sha>`, and
   `parloq-flow-wa-gateway-local:<sha>` for `linux/amd64`.
3. Export only those images, gzip the archive, calculate SHA-256, upload it to
   `root@216.106.185.81`, verify the remote checksum, and load it with Docker.
4. Back up the production `.env` with the commit and UTC timestamp. Change only
   the three image variables during a normal release; preserve all secrets and
   operational settings.
5. Validate with
   `docker compose --env-file .env -f docker-compose.yaml config --quiet`.
6. Run the one-shot `migrate` service and require a zero exit code before
   recreating `api`, `api-worker`, `wa-gateway`, and `web`.
7. Never recreate, delete, or clear PostgreSQL/Redis data as part of a release.
   Never use `docker compose down -v`, and never delete `/data/parloq-flow`.
8. Verify image revisions, migration status, health, restart counts,
   `http://127.0.0.1:18100/healthz`, public HTTPS when DNS is ready, and recent
   error logs.
9. Keep prior image tags and the `.env` backup until verification passes. On
   failure, restore the previous image variables and recreate only application
   services; report the failure and rollback result.
10. Remove local and remote transfer archives after checksum verification and
    a successful release.

The checked-in production Compose and Nginx files are bootstrap/reference
configuration. After the first deployment, inspect live files and never
overwrite them automatically merely to make them match the repository.

## Domains and Nginx

- `center.parloq.com` has its own exact Nginx server block pointing to
  `127.0.0.1:18100`; it must not be added to the old application's upstream.
- The existing wildcard `parloq.com` vhost belongs to the old system. An exact
  `center.parloq.com` block takes precedence and preserves isolation.
- The origin follows the existing Cloudflare-only ingress policy. DNS changes
  happen in Cloudflare and must direct `center.parloq.com` to this production
  origin before public verification.
- Each customer landing-page domain needs DNS pointing at the ingress and an
  explicit Nginx vhost/certificate. Do not install a global default vhost that
  could capture unrelated sites on the shared server.
- `PROMOTION_INGRESS_HOST=center.parloq.com` is the canonical DNS verification
  target; it does not mean customer landing pages must use the system domain.

Detailed bootstrap, release, rollback, DNS, and customer-domain instructions
are in `docs/production-deployment.md`.
