# Baileys WhatsApp gateway

Node/TypeScript replacement for the original Go/whatsmeow data plane. Baileys
7 is the only production protocol engine; `WA_ENGINE=mock` is retained for
local and automated tests and never contacts WhatsApp.

## Persistence and security

- Account control state, message status, Baileys credentials and every Signal
  key-store category are persisted in PostgreSQL under
  `wa_gateway_baileys`.
- Each socket receives the account's fixed HTTP/SOCKS proxy before pairing or
  reconnecting. Changing phone/proxy while connected or pairing is rejected.
- API responses mask proxy credentials. Pino redaction covers bearer tokens,
  session bundles, credentials and key stores. Never enable raw Baileys event
  logging in production.
- The database contains account-takeover-grade secrets. Production deployments
  must use encrypted disks/backups, restricted DB roles and TLS.

## API compatibility

The gateway preserves the former REST shape:

- `GET /healthz`, `GET /readyz`, `GET /metrics`
- `POST/GET /v1/accounts`, `GET/PATCH /v1/accounts/:id`
- `POST /v1/accounts/:id/pairing-code`
- `POST /v1/accounts/:id/connect|disconnect|logout`
- `POST /v1/accounts/:id/messages`, `GET /v1/messages/:id`
- `POST /v1/accounts/:id/import-session`
- `GET /v1/accounts/:id/export-session`

All control endpoints use `Authorization: Bearer ...`. Import accepts:

```json
{"session": {"noiseKey": {}, "signedIdentityKey": {}, "signedPreKey": {}, "advSecretKey": "..."}, "proxyUrl": "socks5://..."}
```

That customer-compatible single-creds form is recorded as
`credentials_only` and `pending_verification`. It is not usable for marketing
until `connect` succeeds. Native gateway export returns a versioned
`parloq-baileys-session/v1` bundle under the top-level `session` property and
contains both credentials and the complete database-backed key store. The
control-plane download API can expose either its nested Baileys `creds` object
for compatibility with other Baileys auth loaders, or the complete bundle for
lossless Parloq-to-Parloq migration.

The control plane does not need to create the gateway account first. When the
path account ID does not exist, import strictly derives its E.164 number from a
Baileys `me.id` shaped like `14155550123:1@s.whatsapp.net` and atomically creates
the account, credentials and key store with the supplied `proxyUrl`. A proxy is
required for this path. Duplicate account IDs or phone numbers return a
conflict and never overwrite existing credentials. Existing accounts retain
the original import/update behavior.

Export is allowed only while disconnected. The response carries
`Cache-Control: no-store`; the control plane should additionally enforce an
admin permission, audit the event and offer a short-lived one-time download.

## Webhooks

Message status and account state callbacks share `WA_GATEWAY_WEBHOOK_URL` and
`WA_GATEWAY_WEBHOOK_SECRET`. Request bodies are signed as
`X-Parloq-Signature: sha256=<HMAC-SHA256(body)>`. State callbacks are emitted
only for actual state changes; retries reuse the same body and event ID:

```json
{
  "event": "account.state",
  "eventId": "ast_58be405d-b932-4f51-9124-cf54091158ed",
  "accountId": "wa_example",
  "fromState": "online_idle",
  "toState": "restricted",
  "reasonCategory": "restricted",
  "providerCode": "403",
  "occurredAt": "2026-08-12T01:02:03.456Z"
}
```

`providerCode` is omitted when Baileys supplies no code. `eventId` is also sent
as `X-Parloq-Event-Id` (and the compatibility `X-Parloq-Message-Id`). Public
account objects expose `stateChangedAt`, `invalidatedAt`, `reasonCategory` and
`providerCode`; only `restricted` sets `invalidatedAt`, while
`reauth_required` remains abnormal but not proven invalid.

## Configuration

The service uses the existing `WA_GATEWAY_*` names. Important values:

```text
WA_ENGINE=mock|baileys
WA_GATEWAY_DATABASE_URL=postgresql://...
WA_GATEWAY_API_TOKEN=... (32+ characters for Baileys)
WA_GATEWAY_WEBHOOK_URL=https://...
WA_GATEWAY_WEBHOOK_SECRET=... (16+ characters when enabled)
```

No real account is contacted by the automated suite. Run `npm test` and
`npm run build` for the mock/control-plane checks.
