# ID conventions

Parloq-generated entity IDs use a signed 64-bit Snowflake layout. The custom
epoch is **2026-08-01 00:00:00 UTC**.

| Segment | Bits | Meaning |
| --- | ---: | --- |
| Timestamp | 41 | Milliseconds since the Parloq epoch |
| Node | 10 | Unique runtime writer identity |
| Sequence | 12 | Per-node sequence within one millisecond |

Internal SQL primary and foreign keys are `BIGINT`. Public business IDs retain
their readable resource prefix and use the same Snowflake value, for example
`ptpl_4780707016605696`, `htsk_4780707016605697`, and
`msg_4780707016605698`. Public IDs must be serialized as strings; JavaScript
must never parse them as `Number` because later values exceed its safe integer
range.

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
