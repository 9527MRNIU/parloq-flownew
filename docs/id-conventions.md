# ID conventions

Parloq-generated entity IDs use a signed 64-bit Snowflake layout. The custom
epoch is **2026-08-01 00:00:00 UTC**.

| Segment | Bits | Meaning |
| --- | ---: | --- |
| Timestamp | 41 | Milliseconds since the Parloq epoch |
| Node | 10 | Unique runtime writer identity |
| Sequence | 12 | Per-node sequence within one millisecond |

Internal SQL primary and foreign keys are `BIGINT`. At HTTP and JavaScript
boundaries the canonical `id` and every related `...Id` are the raw decimal
Snowflake serialized as a string, for example `4780707016605696`. JavaScript
must never parse it as `Number` because later values exceed its safe integer
range.

Historical prefixed aliases such as `ptpl_<snowflake>`, `htsk_<snowflake>`,
`msg_<snowflake>`, and older UUID-shaped values may remain in storage only for
backward compatibility. They are not control-plane IDs, must not be displayed
as system IDs, and must not be returned in the canonical `id` field. A
WhatsApp/Baileys session identifier is explicitly treated as a hidden
`gatewayAccountId`; it does not change when the account's Snowflake ID is used
by the API, UI, tasks, and database relations.

Runtime node allocation:

- `0`: migrations and one-shot maintenance
- `1`: API
- `2`: asynchronous API worker
- `3`: Baileys gateway
- `1000`–`1023`: reserved for historical data migrations

Every additional replica or writer must receive a distinct node ID through its
deployment configuration. Reusing a runtime node across concurrent processes
can create duplicate IDs.

Authentication tokens, verification secrets, idempotency keys supplied by a
client, Signal/Baileys key IDs, and IDs returned by an external provider are
not Parloq entity IDs. They keep their protocol-specific or cryptographically
random format.
