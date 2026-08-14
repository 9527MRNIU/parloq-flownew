import { describe, expect, it, vi } from 'vitest'
import { requestPairingCodeAfterSocketOpen } from './engine.js'

describe('Baileys pairing socket readiness', () => {
  it('waits for the websocket before requesting a pairing code', async () => {
    let openSocket!: () => void
    const socket = {
      waitForSocketOpen: vi.fn(() => new Promise<void>((resolve) => { openSocket = resolve })),
      requestPairingCode: vi.fn(async () => '1234-5678'),
    }

    const pending = requestPairingCodeAfterSocketOpen(socket, '14155550123', 1_000)
    await Promise.resolve()
    expect(socket.requestPairingCode).not.toHaveBeenCalled()

    openSocket()
    await expect(pending).resolves.toBe('1234-5678')
    expect(socket.requestPairingCode).toHaveBeenCalledWith('14155550123')
  })

  it('does not request a code when the websocket closes before opening', async () => {
    const socket = {
      waitForSocketOpen: vi.fn(async () => { throw new Error('Connection Closed') }),
      requestPairingCode: vi.fn(async () => 'should-not-run'),
    }

    await expect(
      requestPairingCodeAfterSocketOpen(socket, '14155550123', 1_000),
    ).rejects.toThrow('Connection Closed')
    expect(socket.requestPairingCode).not.toHaveBeenCalled()
  })

  it('bounds the websocket wait with an explicit timeout', async () => {
    const socket = {
      waitForSocketOpen: vi.fn(() => new Promise<void>(() => undefined)),
      requestPairingCode: vi.fn(async () => 'should-not-run'),
    }

    await expect(
      requestPairingCodeAfterSocketOpen(socket, '14155550123', 5),
    ).rejects.toThrow('timed out waiting for Baileys pairing socket')
    expect(socket.requestPairingCode).not.toHaveBeenCalled()
  })
})
