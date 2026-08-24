# Parloq Flow architecture

## Product boundary

Parloq Flow is a new system, not a rename of the old WABA console. The login,
user and user-group concepts may be migrated, and the frontend should reuse the
old console's interaction language. Features not explicitly listed here should
not be copied.

The current scope is:

- Facebook traffic promotion templates, form/phone collection, pixels and
  delivery analytics;
- personal WhatsApp account pairing and outbound one-to-one message expansion;
- hyperlink tasks, data packages, templates, strategies, materials and market
  insight;
- domain management for promotion template pages;
- account-bound proxy/IP management;
- Bitly direct short links;
- users and user groups.

"Direct short link" means the existing direct Bitly workflow: the system calls
Bitly and stores the returned Bitly short URL. It does **not** mean a new
self-hosted redirect gateway, and the previous self-hosted-to-Bitly indirect
redirect chain must not be migrated.

Pixel management stores/configures pixel IDs and emits browser events from
promotion templates, so it does not require a Meta App. A CAPI token may be
stored encrypted for the later server-event integration, but the current local
runtime does not send CAPI events. Our own Meta App and OAuth become necessary
only when the product must connect customer businesses, enumerate or manage
their Meta assets automatically, or obtain permissions and tokens through a
managed SaaS onboarding flow.

## Capacity envelope

These are design inputs rather than an immediate promise of WhatsApp account
safety or provider throughput:

- up to 100,000 customers who can log in to the management console;
- a theoretical campaign peak of 1,000 concurrently connected sending accounts;
- up to 10 send requests per second per active account for bursts lasting tens
  of seconds to a few minutes;
- no inbound conversation store, reply body, image, video or voice retention;
- outbound status retention stops at server acceptance (one tick) and recipient
  delivery (two ticks); read receipts and replies are ignored.

The theoretical aggregate input can therefore reach 10,000 send requests per
second. Admission control, per-account pacing and campaign backpressure are
mandatory even when infrastructure has spare capacity. Protocol throughput must
not be confused with WhatsApp anti-abuse and account restriction limits.

## Control plane and data plane

The API is the control plane. It owns tenants, users, account configuration,
campaign definitions, templates, proxy allocation, Bitly credentials and
reporting read models. API instances remain stateless and scale horizontally;
PostgreSQL is authoritative and Redis is used for short-lived coordination and
caching.

The Node/TypeScript Baileys gateway is the sending data plane. It owns live WebSocket
connections, pairing, protocol session state, per-account send ordering,
delivery receipt normalization and reconnection. It does not implement console
permissions, campaign editing, analytics queries or general business CRUD.

Campaign recipients enter a durable queue/outbox. Gateway workers claim work by
account, send it through the account owner, and append compact status events.
Database projections update campaign totals asynchronously. Sending and receipt
handling must never synchronously rebuild large reporting views.

## WhatsApp engine boundary

Baileys 7 is the only production protocol adapter. This keeps the account
format aligned with customer-provided Baileys credentials JSON and avoids a
lossy cross-protocol conversion step. The dependency is pinned, and protocol
changes must be verified against a disposable account before upgrading it.

All protocol calls sit behind an internal `Engine` interface. Local Docker uses
a mock implementation for deterministic control-plane development. The
real adapter covers:

- phone-number pairing and session restoration;
- connect, disconnect and logout as separate operations;
- text and link send operations required by the first release;
- server-accepted and delivered receipt normalization;
- proxy application to pairing, WebSocket and media traffic;
- terminal states such as reauthentication required and restricted.

A saved linked-device session does not require a permanent TCP/WebSocket
connection. Accounts may remain in `linked_offline`, connect before a campaign,
send, drain pending delivery receipts and disconnect after an idle timeout.
Disconnect must retain credentials; logout must revoke/delete them and require
pairing again.

## Unified account pool and lifecycle

All accounts live in one tenant-owned account pool regardless of their source:

- `landing_page`: a visitor enters a phone number on a promotion page, receives
  a Baileys pairing code, links the device, and the account is promoted into the
  pool only after the gateway reports a verified connection;
- `json_import`: an operator imports either customer-compatible Baileys creds
  JSON or the system's complete versioned Baileys session bundle.

A customer-compatible creds-only import is intentionally marked
`pending_verification`. Profile, group, friend and mutual-contact metrics remain
unknown until they can be collected online; unknown values must never be
rendered as zero. A native `parloq-baileys-session/v1` export contains both
creds and the account-scoped Signal key store so another Parloq instance can
import it without translating protocols. A separate compatibility download
exposes the Baileys `creds` object at the JSON root for third-party Baileys auth
loaders, accepting that those loaders will rebuild any key-store state they did
not receive.

The canonical states are:

```text
unpaired -> pairing -> linked_offline -> warming -> online_idle
                                      online_idle <-> sending
                                      sending -> draining -> linked_offline

any connected state -> linked_offline     (recoverable disconnect)
any linked state    -> reauth_required     (credentials revoked/corrupt)
any active state    -> restricted          (provider restriction)
any non-sending state -> disabled          (operator action)
```

Campaign accounts should be warmed in bounded batches with jitter. They remain
connected throughout sending and a bounded drain period so two-tick delivery
receipts can be collected. Reconnects use exponential backoff and must not
create a simultaneous 1,000-account handshake storm.

### Operational protocol nodes

The console's “协议管理” is an operational account node, not a selector between
Baileys and another Web protocol. Each tenant-owned node groups accounts and
has independent ingress, marketing and online switches. The ingress switch is
a hard gate for both landing-page linking and JSON import; the marketing
switch is checked when a task is created, started and executed; batch
online/offline connects or disconnects the node's accounts. Node statistics
report total, valid and online accounts, with online rate divided by valid
accounts. Baileys remains the only underlying protocol implementation.

### Account statistics collection boundary

Account-pool daily statistics are derived from signed, idempotent lifecycle
events emitted by the gateway and compact outbound delivery facts. Existing
accounts receive a baseline event when lifecycle collection is introduced.
Dates before `collection_started_at` are not returned because current account
state cannot reconstruct historical unlinks honestly. The first collection day
is marked partial; reporting uses the Asia/Shanghai business-day boundary.
Provider restriction and confirmed logout are invalidation events, while
transient disconnect and `reauth_required` remain separate operational states.
Marketing-before/after-unlink classification requires a successful sent or
delivered record before the invalidation event; queued attempts do not count.

## Exclusive account ownership and session persistence

Exactly one gateway instance may own an account connection at a time:

1. acquire a Redis lease keyed by account ID;
2. atomically allocate a monotonically increasing lease epoch;
3. pass the epoch as a fencing token to every durable session/status write;
4. renew the lease well before its TTL;
5. stop the socket and all account work immediately when renewal fails;
6. reject writes whose epoch is older than the stored epoch.

This retains the useful concurrency invariant from the old system while
removing its WABA API-specific behavior. A lease alone is not enough: a paused
old process can resume after expiry, so PostgreSQL writes must also enforce the
fencing token.

WhatsApp device credentials and every Baileys Signal key-store category are
stored in the gateway's dedicated PostgreSQL schema; local auth files are never
used as the production session store. Credentials are durable across normal
disconnects and gateway restarts. Session deletion is allowed only for an
explicit logout or controlled re-pair operation. The control-plane database
stores account metadata but never a copy of the credentials JSON. Production
PostgreSQL storage and backups must use encryption at rest and dedicated
least-privilege roles because the gateway necessarily needs live key bytes.

## Proxy/IP isolation

An account has one effective proxy assignment at a time. The same assigned
proxy must be used for pairing, reconnect, WebSocket traffic and any media
request. A proxy failure must fail closed: the account becomes unavailable and
must never silently fall back to the host's direct IP.

The allocation policy is tenant-configurable: strict one-account-to-one-IP,
tenant-only reuse, lowest-load preference, or manual assignment. Country
matching uses either the public visitor/access country or the E.164 phone
country. Operators may also configure a per-IP account limit, consecutive
failure threshold, cooldown duration and sticky binding. Reuse never crosses
tenant boundaries when tenant isolation is selected.

Proxy health is event-driven. Import performs one credential-aware gateway
probe against WhatsApp Web; afterward real gateway connections report success
or classified proxy failures. There is no scheduled proxy polling. Active
cooldowns are excluded from every allocation mode, while an expired transient
cooldown re-enters as a low-priority probation candidate. Authentication and
configuration failures remain quarantined until an edit or manual recheck.

## Delivery data

Persist only identifiers and compact delivery facts needed for operations and
statistics:

- tenant, task, account and recipient/message identifiers;
- queued/sent timestamps;
- `server_accepted`, `delivered`, `failed` or `delivery_timeout`;
- normalized failure category and retry metadata.

Do not store inbound messages, reply bodies, read receipts, full chat history or
downloaded inbound media. Status ingestion should append immutable compact
events, then update user-facing counters in batches.

## Local development composition

The default Compose stack contains the Vite web application, API, PostgreSQL,
Redis and the Baileys WhatsApp gateway. The mock protocol engine makes the stack
deterministic and does not require a real phone, while gateway account and
message state still use PostgreSQL. The current single-instance development
gateway does not yet implement the lease/fencing design above; that is required
before production horizontal scaling. Cloud deployment, ClickHouse, Kafka/Redpanda
and autoscaling infrastructure are intentionally outside the local build;
the outbox and event boundaries leave room to introduce them after measured
load justifies the operational cost.
