import pino from 'pino'
import { describe, expect, it, vi } from 'vitest'
import { WaWebVersionResolver } from './wa-version.js'

describe('WA Web version resolution', () => {
  it('uses and caches the current revision served by WhatsApp', async () => {
    const fetchVersion = vi.fn(async () => ({
      version: [2, 3000, 1045195504] as [number, number, number],
      isLatest: true,
    }))
    const resolver = new WaWebVersionResolver(pino({ level: 'silent' }), fetchVersion)

    await expect(resolver.current(undefined, true)).resolves.toEqual([2, 3000, 1045195504])
    await expect(resolver.current(undefined, true)).resolves.toEqual([2, 3000, 1045195504])
    expect(fetchVersion).toHaveBeenCalledTimes(1)
  })

  it('refuses to start a fresh pairing with an unverified bundled fallback', async () => {
    const fetchVersion = vi.fn(async () => ({
      version: [2, 3000, 1] as [number, number, number],
      isLatest: false,
      error: new Error('network unavailable'),
    }))
    const resolver = new WaWebVersionResolver(pino({ level: 'silent' }), fetchVersion)

    await expect(resolver.current(undefined, true)).rejects.toThrow(
      'unable to resolve the current WhatsApp Web client revision',
    )
  })
})
