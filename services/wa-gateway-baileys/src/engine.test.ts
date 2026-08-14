import { EventEmitter } from 'node:events'
import type { ConnectionState } from '@whiskeysockets/baileys'
import { describe, expect, it, vi } from 'vitest'
import { requestStablePairingCode } from './engine.js'

describe('Baileys pairing socket readiness', () => {
  const eventBus = () => {
    const emitter = new EventEmitter()
    return {
      on: (event: 'connection.update', listener: (update: Partial<ConnectionState>) => void) => emitter.on(event, listener),
      off: (event: 'connection.update', listener: (update: Partial<ConnectionState>) => void) => emitter.off(event, listener),
      emit: (event: string, value: unknown) => emitter.emit(event, value),
    }
  }

  it('waits for WhatsApp pair-device readiness before requesting a pairing code', async () => {
    const ev = eventBus()
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev,
    }

    const pending = requestStablePairingCode(socket, '14155550123', 1_000, 1)
    await Promise.resolve()
    expect(socket.requestPairingCode).not.toHaveBeenCalled()

    ev.emit('connection.update', { connection: 'connecting' })
    await Promise.resolve()
    expect(socket.requestPairingCode).not.toHaveBeenCalled()

    ev.emit('connection.update', { qr: 'pair-device-ref' })
    await expect(pending).resolves.toBe('1234-5678')
    expect(socket.requestPairingCode).toHaveBeenCalledWith('14155550123')
  })

  it('does not request a code when the socket closes before pair-device readiness', async () => {
    const ev = eventBus()
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => 'should-not-run'),
      ev,
    }

    const pending = requestStablePairingCode(socket, '14155550123', 1_000, 1)
    ev.emit('connection.update', {
      connection: 'close',
      lastDisconnect: { error: new Error('Connection Closed') },
    })
    await expect(pending).rejects.toThrow('Connection Closed')
    expect(socket.requestPairingCode).not.toHaveBeenCalled()
  })

  it('bounds the pair-device readiness wait with an explicit timeout', async () => {
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => 'should-not-run'),
      ev: eventBus(),
    }

    await expect(
      requestStablePairingCode(socket, '14155550123', 5, 1),
    ).rejects.toThrow('timed out waiting for WhatsApp pairing registration')
    expect(socket.requestPairingCode).not.toHaveBeenCalled()
  })

  it('does not return a locally generated code when WhatsApp closes its socket', async () => {
    const ev = eventBus()
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev,
    }
    const pending = requestStablePairingCode(socket as never, '14155550123', 1_000, 100)
    ev.emit('connection.update', { qr: 'pair-device-ref' })
    await Promise.resolve()
    ev.emit('connection.update', {
      connection: 'close',
      lastDisconnect: { error: new Error('Connection Terminated') },
    })

    await expect(pending).rejects.toThrow('Connection Terminated')
  })

  it('returns the code only after the pairing socket survives the grace period', async () => {
    const ev = eventBus()
    const socket = {
      waitForSocketOpen: vi.fn(async () => undefined),
      requestPairingCode: vi.fn(async () => '1234-5678'),
      ev,
    }

    const pending = requestStablePairingCode(socket as never, '14155550123', 1_000, 5)
    ev.emit('connection.update', { qr: 'pair-device-ref' })
    await expect(pending)
      .resolves.toBe('1234-5678')
  })
})
