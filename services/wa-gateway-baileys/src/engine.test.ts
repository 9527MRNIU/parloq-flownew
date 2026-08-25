import { EventEmitter } from 'node:events'
import {
  BufferJSON,
  initAuthCreds,
  type ConnectionState,
} from '@whiskeysockets/baileys'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  BaileysEngine,
  downloadProfileAvatar,
  hasReconnectableIdentity,
  isRequiredPairingRestart,
  messageTargetJid,
  requestStablePairingCode,
} from './engine.js'
import type { ManagedMediaReference } from './message-content.js'
import type { Store } from './store.js'

afterEach(() => vi.unstubAllGlobals())

describe('Baileys message targets', () => {
  it('maps E.164 recipients and preserves WhatsApp JIDs', () => {
    expect(messageTargetJid('+14155550123')).toBe('14155550123@s.whatsapp.net')
    expect(messageTargetJid('14155550123@s.whatsapp.net')).toBe('14155550123@s.whatsapp.net')
    expect(messageTargetJid('120363000000001@g.us')).toBe('120363000000001@g.us')
  })
})

describe('Baileys pairing restart classification', () => {
  it('accepts pair-success identity credentials even before registered is true', () => {
    const creds = { registered: false, me: { id: '14155550123:1@s.whatsapp.net' }, account: {} }
    expect(hasReconnectableIdentity(creds)).toBe(true)
    expect(isRequiredPairingRestart(515, true, creds)).toBe(true)
  })

  it('does not reconnect temporary phone-code credentials before pair-success', () => {
    const creds = { registered: false, me: { id: '14155550123@s.whatsapp.net' } }
    expect(hasReconnectableIdentity(creds)).toBe(false)
    expect(isRequiredPairingRestart(515, false, creds)).toBe(false)
  })
})

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

describe('Baileys intentional disconnect handling', () => {
  it.each([
    { closeOnline: true, markOnlineOnConnect: false },
    { closeOnline: false, markOnlineOnConnect: true },
  ])('maps closeOnline=$closeOnline and does not classify shutdown as a bad session', async ({ closeOnline, markOnlineOnConnect }) => {
    const emitter = new EventEmitter()
    const socket = {
      ev: {
        on: (event: string, listener: (...args: unknown[]) => void) => emitter.on(event, listener),
        off: (event: string, listener: (...args: unknown[]) => void) => emitter.off(event, listener),
      },
      user: { id: '14155550123:1@s.whatsapp.net' },
      profilePictureUrl: vi.fn(async () => 'https://pps.whatsapp.net/avatar.jpg'),
      end: vi.fn((error: Error) => {
        emitter.emit('connection.update', {
          connection: 'close',
          lastDisconnect: { error },
        })
      }),
    }
    const storedCreds = JSON.parse(JSON.stringify({
      ...initAuthCreds(),
      registered: true,
      me: { id: socket.user.id, name: 'Test' },
    }, BufferJSON.replacer)) as unknown
    const store = {
      getCreds: vi.fn(async () => storedCreds),
      setCreds: vi.fn(async () => undefined),
      getKeys: vi.fn(async () => ({})),
      setKeys: vi.fn(async () => undefined),
      clearAuth: vi.fn(async () => undefined),
    } as unknown as Store
    const baileys = {
      ...(await import('@whiskeysockets/baileys')),
      default: vi.fn(() => {
        queueMicrotask(() => emitter.emit('connection.update', { connection: 'open' }))
        return socket
      }),
      fetchLatestWaWebVersion: vi.fn(async () => ({
        version: [2, 3000, 1023],
        isLatest: true,
      })),
    }
    const avatarDownloader = vi.fn(async () => ({
      contentType: 'image/jpeg',
      size: 4,
      sha256: 'avatar-sha256',
      dataBase64: '/9j/4A==',
    }))
    const engine = new BaileysEngine(store, undefined, 'http://api:8000', baileys as never, avatarDownloader)
    const events: string[] = []
    engine.setEventHandler((event) => { events.push(event.kind) })
    await engine.start()
    await engine.connect({
      accountId: 'wa_shutdown',
      protocolDefinitionId: '0',
      protocolVersion: '6.7.24',
      phoneE164: '+14155550123',
      proxyUrl: '',
      syncPolicy: {
        closeOnline,
        avatar: true,
        groupDetails: true,
        contacts: true,
      },
    })

    expect(baileys.default).toHaveBeenCalledWith(expect.objectContaining({
      markOnlineOnConnect,
      syncFullHistory: false,
    }))
    const normalSocketOptions = (baileys.default.mock.calls[0] as unknown as [{
      shouldSyncHistoryMessage: (message: unknown) => boolean
    }])[0]
    expect(normalSocketOptions.shouldSyncHistoryMessage({})).toBe(false)
    await expect(engine.getQuality('wa_shutdown', {
      closeOnline,
      avatar: true,
      groupDetails: false,
      contacts: false,
    })).resolves.toMatchObject({
      hasAvatar: true,
      avatar: {
        sourceUrl: 'https://pps.whatsapp.net/avatar.jpg',
        contentType: 'image/jpeg',
        dataBase64: '/9j/4A==',
      },
    })
    expect(socket.profilePictureUrl).toHaveBeenCalledWith(socket.user.id, 'image')
    expect(avatarDownloader).toHaveBeenCalledWith('https://pps.whatsapp.net/avatar.jpg', undefined)
    await engine.close()

    expect(socket.end).toHaveBeenCalledWith(expect.objectContaining({ message: 'gateway disconnect' }))
    expect(events).toEqual(['connected'])
  })

  it('requests history only for an explicit metadata run and deduplicates saved and contacted identities', async () => {
    const emitter = new EventEmitter()
    const socket = {
      ev: {
        on: (event: string, listener: (...args: unknown[]) => void) => emitter.on(event, listener),
        off: (event: string, listener: (...args: unknown[]) => void) => emitter.off(event, listener),
      },
      user: { id: '14155550123:1@s.whatsapp.net' },
      profilePictureUrl: vi.fn(async () => undefined),
      end: vi.fn((error: Error) => {
        emitter.emit('connection.update', {
          connection: 'close',
          lastDisconnect: { error },
        })
      }),
    }
    const storedCreds = JSON.parse(JSON.stringify({
      ...initAuthCreds(),
      registered: true,
      platform: 'smbi',
      me: { id: socket.user.id, name: 'Business test' },
    }, BufferJSON.replacer)) as unknown
    const store = {
      getCreds: vi.fn(async () => storedCreds),
      setCreds: vi.fn(async () => undefined),
      getKeys: vi.fn(async () => ({})),
      setKeys: vi.fn(async () => undefined),
      clearAuth: vi.fn(async () => undefined),
    } as unknown as Store
    const baileys = {
      ...(await import('@whiskeysockets/baileys')),
      default: vi.fn(() => {
        queueMicrotask(() => emitter.emit('connection.update', { connection: 'open' }))
        return socket
      }),
      fetchLatestWaWebVersion: vi.fn(async () => ({
        version: [2, 3000, 1023],
        isLatest: true,
      })),
    }
    const engine = new BaileysEngine(store, undefined, 'http://api:8000', baileys as never)
    await engine.start()
    await engine.connect({
      accountId: 'wa_resource_sync',
      protocolDefinitionId: '0',
      protocolVersion: '6.7.24',
      phoneE164: '+14155550123',
      proxyUrl: '',
      syncPolicy: {
        closeOnline: true,
        avatar: false,
        groupDetails: false,
        contacts: true,
      },
      metadata: { requestContactsHistory: true },
    })

    const socketOptions = (baileys.default.mock.calls[0] as unknown as [{
      syncFullHistory: boolean
      shouldSyncHistoryMessage: (message: unknown) => boolean
    }])[0]
    expect(socketOptions).toEqual(expect.objectContaining({ syncFullHistory: true }))
    expect(socketOptions.shouldSyncHistoryMessage({})).toBe(true)

    emitter.emit('messaging-history.set', {
      contacts: [
        { id: '11111111111@lid', lid: '11111111111@lid', name: 'Saved Alice' },
      ],
      messages: [
        {
          key: {
            remoteJid: '11111111111@lid',
            senderLid: '11111111111@lid',
            senderPn: '14155550101@s.whatsapp.net',
          },
          pushName: 'Alice',
          messageTimestamp: 1_700_000_000,
        },
        {
          key: { remoteJid: '14155550102@s.whatsapp.net' },
          pushName: 'Bob',
          messageTimestamp: 1_700_000_001,
        },
      ],
      isLatest: true,
      progress: 100,
    })

    const quality = await engine.getQuality('wa_resource_sync', {
      closeOnline: true,
      avatar: false,
      groupDetails: false,
      contacts: true,
    })
    expect(quality.friendCount).toBe(2)
    expect(quality.resources.contactsStatus).toBe('complete')
    expect(quality.resources.contactsComplete).toBe(true)
    expect(quality.resources.accountType).toBe('business')
    expect(quality.resources.deviceOs).toBe('ios')
    expect(quality.resources.contacts).toEqual(expect.arrayContaining([
      expect.objectContaining({
        contactId: '14155550101@s.whatsapp.net',
        jid: '14155550101@s.whatsapp.net',
        lid: '11111111111@lid',
        isSavedContact: true,
        hasChatHistory: true,
      }),
      expect.objectContaining({
        contactId: '14155550102@s.whatsapp.net',
        isSavedContact: false,
        hasChatHistory: true,
      }),
    ]))
    await engine.close()
  })

  it('rejects non-HTTPS profile avatar URLs before making a request', async () => {
    await expect(downloadProfileAvatar('http://127.0.0.1/avatar.jpg'))
      .rejects.toThrow('profile avatar URL is invalid')
  })
})

describe('managed material delivery', () => {
  const reference = (sha256: string): ManagedMediaReference => ({
    id: '4780486454931715',
    token: 'signed-material-token',
    fileName: 'banner.png',
    mimeType: 'image/png',
    size: 4,
    sha256,
  })

  const fetchMaterial = (engine: BaileysEngine, media: ManagedMediaReference) =>
    (engine as unknown as {
      fetchManagedMaterial(value: ManagedMediaReference): Promise<Buffer>
    }).fetchManagedMaterial(media)

  it('downloads a signed managed material and verifies its bytes', async () => {
    const bytes = Buffer.from('test')
    const digest = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
    const request = vi.fn(async () => new Response(bytes))
    vi.stubGlobal('fetch', request)
    const engine = new BaileysEngine({} as Store, undefined, 'http://api:8000')

    await expect(fetchMaterial(engine, reference(digest))).resolves.toEqual(bytes)
    expect(request).toHaveBeenCalledWith(
      'http://api:8000/api/internal/materials/4780486454931715/content',
      expect.objectContaining({
        headers: { Authorization: 'Bearer signed-material-token' },
      }),
    )
  })

  it('rejects managed material bytes when the checksum changes', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(Buffer.from('test'))))
    const engine = new BaileysEngine({} as Store, undefined, 'http://api:8000')

    await expect(fetchMaterial(engine, reference('a'.repeat(64))))
      .rejects.toThrow('checksum changed')
  })
})
