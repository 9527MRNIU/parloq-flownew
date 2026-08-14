export const SNOWFLAKE_EPOCH_MS = Date.UTC(2026, 7, 1, 0, 0, 0, 0)
const NODE_BITS = 10n
const SEQUENCE_BITS = 12n
const MAX_NODE_ID = Number((1n << NODE_BITS) - 1n)
const MAX_SEQUENCE = (1n << SEQUENCE_BITS) - 1n
const MAX_TIMESTAMP_DELTA = (1n << 41n) - 1n

export class SnowflakeGenerator {
  private lastTimestamp = -1
  private sequence = 0n

  constructor(
    readonly nodeId: number,
    private readonly clockMs: () => number = Date.now,
  ) {
    if (!Number.isInteger(nodeId) || nodeId < 0 || nodeId > MAX_NODE_ID) {
      throw new Error(`SNOWFLAKE_NODE_ID must be an integer between 0 and ${MAX_NODE_ID}`)
    }
  }

  nextId(): bigint {
    let now = this.clockMs()
    if (now < SNOWFLAKE_EPOCH_MS) throw new Error('system clock is before the 2026-08-01 Snowflake epoch')
    if (now < this.lastTimestamp) now = this.lastTimestamp

    if (now === this.lastTimestamp) {
      this.sequence = (this.sequence + 1n) & MAX_SEQUENCE
      if (this.sequence === 0n) now = this.waitNextMillisecond(this.lastTimestamp)
    } else {
      this.sequence = 0n
    }

    const delta = BigInt(now - SNOWFLAKE_EPOCH_MS)
    if (delta > MAX_TIMESTAMP_DELTA) throw new Error('Snowflake timestamp has exhausted its 41-bit range')
    this.lastTimestamp = now
    return (delta << (NODE_BITS + SEQUENCE_BITS)) | (BigInt(this.nodeId) << SEQUENCE_BITS) | this.sequence
  }

  private waitNextMillisecond(previous: number): number {
    let now = this.clockMs()
    while (now <= previous) now = this.clockMs()
    return now
  }
}

function configuredNodeId(): number {
  const raw = (process.env.SNOWFLAKE_NODE_ID || '3').trim()
  const parsed = Number(raw)
  if (!Number.isInteger(parsed)) throw new Error('SNOWFLAKE_NODE_ID must be an integer')
  return parsed
}

const generator = new SnowflakeGenerator(configuredNodeId())

export function nextSnowflakeId(): string {
  return generator.nextId().toString()
}

export function newPublicId(prefix: string): string {
  const normalized = prefix.trim().toLowerCase()
  if (!normalized || !/^[a-z0-9-]+$/.test(normalized)) throw new Error('invalid public ID prefix')
  return `${normalized}_${nextSnowflakeId()}`
}
