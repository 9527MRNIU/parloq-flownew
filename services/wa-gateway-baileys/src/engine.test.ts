import { EventEmitter } from 'node:events'
import type { ConnectionState } from '@whiskeysockets/baileys'
import { describe, expect, it, vi } from 'vitest'
import { requestPairingCodeAfterSocketOpen, requestStablePairingCode } from './engine.js'

describe('Baileys pairing socket readiness', () => {
  const eventBus = () => {
    const emitter = new EventEmitter()
    return {
      on: (event: 'connection.update', listener: (update: Partial<ConnectionState>) => void) => emitter.on(event, listener),
      off: (event: 'connection.update', listener: (update: Partial<ConnectionState>) => void) => emitter.off(event, listener),
      emit: (event: string, value: unknown) => emitter.emit(event, value),
    }
  }

  it('waits for the websocket before requesting a pairing code', async () => {
    let openSocket!: () => void
    const socket = {
      waitForSocketOpen: vi.fn(() => new Promise<void>((resolve) => { openSocket = resolve })),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev: eventBus(),
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
      ev: eventBus(),
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
      ev: eventBus(),
    }

    await expect(
      requestPairingCodeAfterSocketOpen(socket, '14155550123', 5),
    ).rejects.toThrow('timed out waiting for Baileys pairing socket')
    expect(socket.requestPairingCode).not.toHaveBeenCalled()
  })

  it('does not return a locally generated code when WhatsApp closes its socket', async () => {
    const ev = eventBus()
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev,
    }
    const pending = requestStablePairingCode(socket as never, '14155550123', 100)
    ev.emit('connection.update', {
      connection: 'close',
      lastDisconnect: { error: new Error('Connection Terminated') },
    })

    await expect(pending).rejects.toThrow('Connection Terminated')
  })

  it('returns the code only after the pairing socket survives the grace period', async () => {
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev: eventBus(),
    }

    await expect(requestStablePairingCode(socket as never, '14155550123', 5))
      .resolves.toBe('1234-5678')
  })
})
