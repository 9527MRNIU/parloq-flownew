# WhatsApp gateway

The gateway is the connection-oriented sending data plane for personal
WhatsApp accounts. Local Docker defaults to `WA_ENGINE=mock`; production and
real account testing use the compiled `WA_ENGINE=whatsmeow` adapter.

## Guarantees and boundaries

- A linked-device session is persisted in PostgreSQL and restored after a
  normal process restart.
- `disconnect` closes the socket and preserves the session. A later `connect`
  does not require pairing unless WhatsApp or the phone revoked the device.
- `logout` unlinks and removes the saved device session. Pairing is required
  again.
- One Redis lease owns each account. A monotonically increasing epoch fences
  stale account/status writes.
- Each account has one ordered queue with a strict configurable maximum of 10
  sends per second. `WA_GATEWAY_CONCURRENT_SENDS` caps aggregate workers.
- HTTP/SOCKS5 proxy configuration is fixed per account and applied before the
  pairing or reconnect socket is opened. API responses mask proxy credentials;
  logs never include proxy URLs.
- Message text exists only in the bounded in-memory send job. PostgreSQL stores
  identifiers and `queued`, `sent`, `delivered` or `failed`, not message bodies,
  replies, chats or media.
- Read receipts are accepted internally but collapse to `delivered`; the
  control plane exposes only one-tick `sent` and two-tick `delivered`.

## REST API

The examples assume the local token from `.env.example`:

```bash
export WA_TOKEN=local-wa-gateway-token-change-before-shared-environment
export WA_API=http://127.0.0.1:8010
```

Create and inspect an account:

```bash
curl -fsS -H "Authorization: Bearer $WA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"phoneE164":"+14155550123","proxyUrl":"socks5://user:pass@proxy.example:1080"}' \
  "$WA_API/v1/accounts"

curl -fsS -H "Authorization: Bearer $WA_TOKEN" "$WA_API/v1/accounts"
curl -fsS -H "Authorization: Bearer $WA_TOKEN" "$WA_API/v1/accounts/ACCOUNT_ID"
```

Change the fixed proxy only while the account is disconnected. Online or
pairing accounts return HTTP 409 so a live WebSocket can never drift to a new
IP mid-session:

```bash
curl -fsS -X PATCH -H "Authorization: Bearer $WA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"proxyUrl":"socks5://new-user:new-pass@proxy.example:1080"}' \
  "$WA_API/v1/accounts/ACCOUNT_ID"
```

Request a phone pairing code and connect:

```bash
curl -fsS -H "Authorization: Bearer $WA_TOKEN" \
  -H 'Content-Type: application/json' -d '{}' \
  "$WA_API/v1/accounts/ACCOUNT_ID/pairing-code"

curl -fsS -X POST -H "Authorization: Bearer $WA_TOKEN" \
  "$WA_API/v1/accounts/ACCOUNT_ID/connect"
```

Send idempotently. Reusing the same `messageId`, account and recipient returns
the existing row rather than sending twice:

```bash
curl -fsS -H "Authorization: Bearer $WA_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"messageId":"test-0001","toE164":"+14155550124","text":"hello"}' \
  "$WA_API/v1/accounts/ACCOUNT_ID/messages"

curl -fsS -H "Authorization: Bearer $WA_TOKEN" \
  "$WA_API/v1/messages/test-0001"
```

Recoverable disconnect versus destructive logout:

```bash
curl -fsS -X POST -H "Authorization: Bearer $WA_TOKEN" \
  "$WA_API/v1/accounts/ACCOUNT_ID/disconnect"

curl -fsS -X POST -H "Authorization: Bearer $WA_TOKEN" \
  "$WA_API/v1/accounts/ACCOUNT_ID/logout"
```

## Real whatsmeow pairing test

1. Use a disposable WhatsApp account and a test proxy. Unofficial WhatsApp Web
   libraries can trigger restrictions and have no provider SLA.
2. Set `WA_ENGINE=whatsmeow` in `.env`; keep PostgreSQL and Redis unchanged.
3. Run `docker compose up -d --build wa-gateway` and verify `/readyz` reports
   `whatsmeow`.
4. Create the gateway account with its fixed proxy, then call
   `/pairing-code`. The API returns a short-lived code.
5. On the phone, open **Linked devices**, choose **Link with phone number**, and
   enter the code before `expiresAt`.
6. Poll `GET /v1/accounts/ACCOUNT_ID` until state is `online_idle`, send one
   test message, and poll its message status.
7. Call `disconnect`, restart the gateway container, then call `connect`. It
   should reconnect from PostgreSQL without another pairing code.
8. Call `logout` only when intentionally testing unlink/re-pair behavior.

No real phone or WhatsApp account is available in automated local tests, so
pair-code acceptance, restriction behavior and real delivery receipts are not
claimed as verified. CI verifies compilation of the pinned official whatsmeow
commit, mock REST behavior, lease/rate primitives and a baseline scheduler test
for 1,000 logical accounts × 10 messages at 10 QPS per account.

## Signed status callback

When `WA_GATEWAY_WEBHOOK_URL` is set, every public status transition is sent as
JSON with:

- `X-Parloq-Signature: sha256=<hex HMAC-SHA256>` over the exact body;
- `X-Parloq-Message-Id` as the idempotency key.

The receiving control plane must verify the signature before parsing the body
and upsert by `(messageId, status)`. Configure the shared secret through
`WA_GATEWAY_WEBHOOK_SECRET`; it is never logged.
