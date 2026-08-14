import { describe, expect, it } from 'vitest'

import { SNOWFLAKE_EPOCH_MS, SnowflakeGenerator } from './snowflake.js'

describe('SnowflakeGenerator', () => {
  it('uses the 2026-08-01 epoch, node and sequence layout', () => {
    const generator = new SnowflakeGenerator(37, () => SNOWFLAKE_EPOCH_MS + 12_345)
    const first = generator.nextId()
    const second = generator.nextId()

    expect(first >> 22n).toBe(12_345n)
    expect((first >> 12n) & 1023n).toBe(37n)
    expect(first & 4095n).toBe(0n)
    expect(second & 4095n).toBe(1n)
  })
})
