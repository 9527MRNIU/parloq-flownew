import { BufferJSON, initAuthCreds } from '@whiskeysockets/baileys'
import { createHmac } from 'node:crypto'
import pino from 'pino'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GatewayError, type Account, type AccountState, type Message, type StoredAuth, type StoredKey } from './domain.js'
import { MockEngine, type AccountQuality, type EngineAccount, type EngineEvent, type PairResult, type ProtocolEngine } from './engine.js'
import { buildServer } from './http.js'
import { GatewayService } from './service.js'
import type { Store } from './store.js'
import { WebhookClient } from './webhook.js'

class MemoryStore implements Store {
  accounts = new Map<string, Account>()
  messages = new Map<string, Message>()
  creds = new Map<string, unknown>()
  keys = new Map<string, StoredKey>()
  async migrate() {}
  async ready() {}
  async close() {}
  async createAccount(input: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state'>): Promise<Account> {
    if (this.accounts.has(input.id) || [...this.accounts.values()].some((account) => account.phoneE164 === input.phoneE164)) {
      throw new GatewayError('conflict', 'duplicate')
    }
    const now = new Date()
    const account: Account = { ...input, deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'idle', pairingExpiresAt: null, metadataSyncStatus: 'pending', hasAvatar: null, groupCount: null, friendCount: null, mutualContactCount: null, stateChangedAt: now, invalidatedAt: null, reasonCategory: 'created', providerCode: null, createdAt: now, updatedAt: now }
    this.accounts.set(account.id, account)
    return account
  }
  async claimUnpairedAccount(input: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl'>): Promise<Account | null> {
    const current = [...this.accounts.values()].find((account) => account.phoneE164 === input.phoneE164)
    if (!current || current.id === input.id || current.state !== 'unpaired' || current.deviceJid || current.sessionStatus !== 'none' || this.creds.has(current.id)) return null
    if ([...this.keys.keys()].some((id) => id.startsWith(`${current.id}:`)) || [...this.messages.values()].some((message) => message.accountId === current.id)) return null
    this.accounts.delete(current.id)
    const claimed = { ...current, id: input.id, proxyUrl: input.proxyUrl, reasonCategory: 'orphan_reclaimed', providerCode: null, updatedAt: new Date() }
    this.accounts.set(claimed.id, claimed)
    return claimed
  }
  async createImportedAccount(input: Pick<Account, 'id' | 'phoneE164' | 'proxyUrl' | 'state' | 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness'>, auth: StoredAuth) {
    if (this.accounts.has(input.id) || [...this.accounts.values()].some((account) => account.phoneE164 === input.phoneE164)) throw new GatewayError('conflict', 'duplicate')
    const now = new Date()
    const account: Account = {
      ...input,
      pairingStatus: 'idle',
      pairingExpiresAt: null,
      metadataSyncStatus: 'pending',
      hasAvatar: null,
      groupCount: null,
      friendCount: null,
      mutualContactCount: null,
      stateChangedAt: now,
      invalidatedAt: null,
      reasonCategory: 'session_imported',
      providerCode: null,
      createdAt: now,
      updatedAt: now,
    }
    this.accounts.set(account.id, account)
    await this.replaceAuth(account.id, auth)
    return account
  }
  async listAccounts() { return [...this.accounts.values()] }
  async getAccount(id: string) { const value = this.accounts.get(id); if (!value) throw new GatewayError('not_found', 'missing'); return value }
  async updateAccount(id: string, changes: Partial<Account>) { const current = await this.getAccount(id); const value = { ...current, ...changes, updatedAt: new Date() }; this.accounts.set(id, value); return value }
  async transitionAccount(id: string, state: AccountState, changes: Partial<Account>, reasonCategory: string, providerCode?: string) {
    const current = await this.getAccount(id)
    const changed = current.state !== state
    const now = new Date()
    const account: Account = {
      ...current,
      ...changes,
      state,
      ...(changed ? {
        stateChangedAt: now,
        invalidatedAt: state === 'restricted' ? now : null,
        reasonCategory,
        providerCode: providerCode ?? null,
      } : {}),
      updatedAt: now,
    }
    this.accounts.set(id, account)
    return { account, fromState: current.state, changed }
  }
  async createMessage(message: Message) { const existing = this.messages.get(message.messageId); if (existing) return { message: existing, created: false }; this.messages.set(message.messageId, message); return { message, created: true } }
  async getMessage(id: string) { const value = this.messages.get(id); if (!value) throw new Error('missing'); return value }
  async updateMessage(id: string, changes: Partial<Message>) { const current = await this.getMessage(id); const value = { ...current, ...changes, updatedAt: new Date() }; this.messages.set(id, value); return value }
  async markDeliveredByProvider(accountId: string, providerMessageId: string) { const value = [...this.messages.values()].find((item) => item.accountId === accountId && item.providerMessageId === providerMessageId); return value ? this.updateMessage(value.messageId, { status: 'delivered', deliveredAt: new Date() }) : null }
  async getCreds(id: string) { return this.creds.get(id) ?? null }
  async setCreds(id: string, creds: unknown) { this.creds.set(id, creds) }
  async getKeys(accountId: string, type: string, ids: string[]) { return Object.fromEntries(ids.flatMap((id) => { const value = this.keys.get(`${accountId}:${type}:${id}`); return value ? [[id, value.value]] : [] })) }
  async setKeys(accountId: string, keys: StoredKey[]) { for (const key of keys) { const id = `${accountId}:${key.type}:${key.id}`; if (key.value === null) this.keys.delete(id); else this.keys.set(id, key) } }
  async getAllKeys(accountId: string) { return [...this.keys.entries()].filter(([id]) => id.startsWith(`${accountId}:`)).map(([, key]) => key) }
  async replaceAuth(accountId: string, auth: StoredAuth) { this.creds.set(accountId, auth.creds); for (const id of [...this.keys.keys()]) if (id.startsWith(`${accountId}:`)) this.keys.delete(id); await this.setKeys(accountId, auth.keys) }
  async clearAuth(accountId: string) { this.creds.delete(accountId); for (const id of [...this.keys.keys()]) if (id.startsWith(`${accountId}:`)) this.keys.delete(id) }
}

const token = 'test-token-with-at-least-thirty-two-characters'

class TerminalConnectEngine implements ProtocolEngine {
  readonly name = 'terminal-test'
  private handler: (event: EngineEvent) => void = () => undefined
  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> {}
  async ready(): Promise<void> {}
  async close(): Promise<void> {}
  async pair(_account: EngineAccount): Promise<PairResult> { throw new Error('not implemented') }
  constructor(private readonly terminalKind: 'reauth_required' | 'restricted' = 'restricted') {}
  async connect(account: EngineAccount): Promise<void> {
    this.handler({
      kind: this.terminalKind,
      accountId: account.accountId,
      reasonCategory: this.terminalKind === 'restricted' ? 'restricted' : 'bad_session',
      providerCode: this.terminalKind === 'restricted' ? '403' : '500',
    })
    throw new Error('forbidden')
  }
  async disconnect(_accountId: string): Promise<void> {}
  async logout(_account: EngineAccount): Promise<void> {}
  async send(_accountId: string, _toE164: string, _text: string): Promise<string> { throw new Error('not implemented') }
  async getQuality(_accountId: string): Promise<AccountQuality> { return { hasAvatar: null, groupCount: null, friendCount: null, mutualContactCount: null } }
  isOnline(_accountId: string): boolean { return false }
}

class InterruptedPairingEngine implements ProtocolEngine {
  readonly name = 'interrupted-pairing-test'
  private handler: (event: EngineEvent) => void = () => undefined
  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> {}
  async ready(): Promise<void> {}
  async close(): Promise<void> {}
  async pair(account: EngineAccount): Promise<PairResult> {
    queueMicrotask(() => this.handler({
      kind: 'disconnected',
      accountId: account.accountId,
      reasonCategory: 'protocol_disconnect',
      providerCode: '428',
    }))
    return { accountId: account.accountId, code: 'ABCD-EFGH', expiresAt: new Date(Date.now() + 180_000) }
  }
  async connect(_account: EngineAccount): Promise<void> { throw new Error('not implemented') }
  async disconnect(_accountId: string): Promise<void> {}
  async logout(_account: EngineAccount): Promise<void> {}
  async send(_accountId: string, _toE164: string, _text: string): Promise<string> { throw new Error('not implemented') }
  async getQuality(_accountId: string): Promise<AccountQuality> { return { hasAvatar: null, groupCount: null, friendCount: null, mutualContactCount: null } }
  isOnline(_accountId: string): boolean { return false }
}

describe('Baileys gateway HTTP contract', () => {
  let store: MemoryStore
  let engine: MockEngine
  let service: GatewayService
  let app: ReturnType<typeof buildServer>

  beforeEach(async () => {
    store = new MemoryStore()
    engine = new MockEngine()
    const logger = pino({ level: 'silent' })
    service = new GatewayService(store, engine, new WebhookClient('', '', 0, logger), logger)
    await service.start()
    app = buildServer({ service, apiToken: token, instanceId: 'test', logger })
  })

  afterEach(async () => { await app.close(); await service.close() })

  it('exposes unauthenticated probes and protects control endpoints', async () => {
    expect((await app.inject({ method: 'GET', url: '/healthz' })).statusCode).toBe(200)
    expect((await app.inject({ method: 'GET', url: '/readyz' })).statusCode).toBe(200)
    expect((await app.inject({ method: 'GET', url: '/v1/accounts' })).statusCode).toBe(401)
  })

  it('keeps the legacy account and pairing response shape without leaking proxy credentials', async () => {
    const headers = { authorization: `Bearer ${token}` }
    const created = await app.inject({ method: 'POST', url: '/v1/accounts', headers, payload: { id: 'wa_test', phoneE164: '+14155550123', proxyUrl: 'socks5://user:secret@proxy.example:1080' } })
    expect(created.statusCode).toBe(201)
    expect(created.body).not.toContain('secret')
    const paired = await app.inject({ method: 'POST', url: '/v1/accounts/wa_test/pairing-code', headers, payload: {} })
    expect(paired.statusCode).toBe(200)
    expect(paired.json().data.code).toBe('0000-0000')
  })

  it('reclaims a credential-free orphan left by an interrupted control-plane transaction', async () => {
    const headers = { authorization: `Bearer ${token}` }
    await store.createAccount({ id: 'wa_orphan_old', phoneE164: '+14155550131', proxyUrl: 'socks5://old.example:1080', state: 'unpaired' })

    const claimed = await app.inject({
      method: 'POST',
      url: '/v1/accounts',
      headers,
      payload: { id: 'wa_orphan_new', phoneE164: '+14155550131', proxyUrl: 'socks5://new.example:1080' },
    })

    expect(claimed.statusCode).toBe(201)
    expect(claimed.json().data).toMatchObject({ id: 'wa_orphan_new', state: 'unpaired', reasonCategory: 'orphan_reclaimed' })
    expect(store.accounts.has('wa_orphan_old')).toBe(false)
    expect(store.accounts.has('wa_orphan_new')).toBe(true)
  })

  it('fails an interrupted unverified pairing instead of reusing its stale code', async () => {
    const isolatedStore = new MemoryStore()
    const interruptedEngine = new InterruptedPairingEngine()
    const logger = pino({ level: 'silent' })
    const isolatedService = new GatewayService(isolatedStore, interruptedEngine, new WebhookClient('', '', 0, logger), logger)
    await isolatedService.start()
    try {
      await isolatedService.createAccount({ id: 'wa_interrupted_pairing', phoneE164: '+14155550132', proxyUrl: 'socks5://proxy.example:1080' })
      const pairing = await isolatedService.requestPairingCode('wa_interrupted_pairing')
      expect(pairing.code).toBe('ABCD-EFGH')
      await new Promise((resolve) => setTimeout(resolve, 0))

      const account = await isolatedStore.getAccount('wa_interrupted_pairing')
      expect(account).toMatchObject({
        state: 'unpaired',
        pairingStatus: 'failed',
        sessionStatus: 'none',
        sessionCompleteness: 'none',
        deviceJid: '',
        reasonCategory: 'pairing_connection_lost',
      })
      const cancelled = await isolatedService.cancelPairing('wa_interrupted_pairing')
      expect(cancelled).toMatchObject({
        state: 'unpaired',
        pairingStatus: 'failed',
        sessionStatus: 'none',
      })
    } finally {
      await isolatedService.close()
    }
  })

  it('recovers legacy interrupted pairing credentials before issuing a fresh code', async () => {
    await store.createAccount({ id: 'wa_legacy_pairing', phoneE164: '+14155550133', proxyUrl: 'socks5://proxy.example:1080', state: 'linked_offline' })
    await store.setCreds('wa_legacy_pairing', { temporary: true })

    const pairing = await service.requestPairingCode('wa_legacy_pairing')

    expect(pairing.code).toBe('0000-0000')
    expect(await store.getCreds('wa_legacy_pairing')).toBeNull()
    expect(await store.getAccount('wa_legacy_pairing')).toMatchObject({
      state: 'online_idle',
      sessionStatus: 'verified',
      pairingStatus: 'verified',
      reasonCategory: 'connected',
    })
  })

  it('does not replace imported credentials that are still awaiting verification', async () => {
    await store.createAccount({ id: 'wa_pending_import', phoneE164: '+14155550134', proxyUrl: 'socks5://proxy.example:1080', state: 'linked_offline' })
    await store.updateAccount('wa_pending_import', { sessionStatus: 'pending_verification', sessionCompleteness: 'credentials_only' })
    const importedCreds = { imported: true }
    await store.setCreds('wa_pending_import', importedCreds)

    await expect(service.requestPairingCode('wa_pending_import')).rejects.toThrow('account already has a session')
    expect(await store.getCreds('wa_pending_import')).toBe(importedCreds)
  })

  it('imports legacy Baileys creds as pending and exports a complete versioned bundle', async () => {
    const headers = { authorization: `Bearer ${token}` }
    const creds = initAuthCreds()
    creds.me = { id: '14155550124:1@s.whatsapp.net', name: 'Imported' }
    const legacyJson = JSON.parse(JSON.stringify({ Phone: '14155550124', ...creds }, (_key, value) => {
      if (Buffer.isBuffer(value) || value instanceof Uint8Array) return { type: 'Buffer', data: [...value] }
      return value
    }))
    const imported = await app.inject({ method: 'POST', url: '/v1/accounts/wa_import/import-session', headers, payload: { session: legacyJson, proxyUrl: 'socks5://proxy.example:1080' } })
    expect(imported.statusCode).toBe(200)
    expect(imported.json().status).toBe('pending_verification')
    expect(imported.json().account.sessionCompleteness).toBe('credentials_only')
    expect(imported.json().account.phoneE164).toBe('+14155550124')

    await store.setKeys('wa_import', [{ type: 'pre-key', id: '1', value: JSON.parse(JSON.stringify({ private: Buffer.alloc(32), public: Buffer.alloc(32) }, BufferJSON.replacer)) }])
    const exported = await app.inject({ method: 'GET', url: '/v1/accounts/wa_import/export-session', headers })
    expect(exported.statusCode).toBe(200)
    expect(exported.headers['cache-control']).toBe('no-store')
    const session = exported.json().session
    expect(session.format).toBe('parloq-baileys-session')
    expect(session.version).toBe(1)
    expect(session.library).toEqual({ name: '@whiskeysockets/baileys', version: '6.7.24' })
    expect(session.auth.keys).toHaveLength(1)

    const roundTripImport = await app.inject({ method: 'POST', url: '/v1/accounts/wa_roundtrip/import-session', headers, payload: { session, proxyUrl: 'socks5://proxy-2.example:1080' } })
    expect(roundTripImport.statusCode).toBe(409)

    session.auth.creds.me.id = '14155550127:2@s.whatsapp.net'
    const distinctImport = await app.inject({ method: 'POST', url: '/v1/accounts/wa_roundtrip/import-session', headers, payload: { session, proxyUrl: 'socks5://proxy-2.example:1080' } })
    expect(distinctImport.statusCode).toBe(200)
    expect(distinctImport.json().account.sessionCompleteness).toBe('full')
    const exportedAgain = await app.inject({ method: 'GET', url: '/v1/accounts/wa_roundtrip/export-session', headers })
    expect(exportedAgain.statusCode).toBe(200)
    expect(exportedAgain.json().session.auth).toEqual(session.auth)
  })

  it('queues a text message idempotently in mock mode', async () => {
    const headers = { authorization: `Bearer ${token}` }
    await app.inject({ method: 'POST', url: '/v1/accounts', headers, payload: { id: 'wa_send', phoneE164: '+14155550125' } })
    await app.inject({ method: 'POST', url: '/v1/accounts/wa_send/pairing-code', headers, payload: {} })
    await new Promise((resolve) => setTimeout(resolve, 0))
    const request = { method: 'POST' as const, url: '/v1/accounts/wa_send/messages', headers, payload: { messageId: 'msg-1', toE164: '+14155550126', text: 'hello' } }
    expect((await app.inject(request)).statusCode).toBe(202)
    expect((await app.inject(request)).statusCode).toBe(202)
    await new Promise((resolve) => setTimeout(resolve, 5))
    const status = await app.inject({ method: 'GET', url: '/v1/messages/msg-1', headers })
    expect(status.json().data.status).toBe('sent')
  })

  it('does not let connect or disconnect erase a terminal account state', async () => {
    const headers = { authorization: `Bearer ${token}` }
    await app.inject({ method: 'POST', url: '/v1/accounts', headers, payload: { id: 'wa_restricted', phoneE164: '+14155550128' } })
    await store.setCreds('wa_restricted', { registered: true })
    await store.transitionAccount('wa_restricted', 'restricted', { deviceJid: '14155550128:1@s.whatsapp.net' }, 'restricted', '403')

    expect((await app.inject({ method: 'POST', url: '/v1/accounts/wa_restricted/connect', headers })).statusCode).toBe(409)
    const disconnected = await app.inject({ method: 'POST', url: '/v1/accounts/wa_restricted/disconnect', headers })
    expect(disconnected.statusCode).toBe(200)
    expect(disconnected.json().data.state).toBe('restricted')
    expect(disconnected.json().data.autoConnect).toBe(false)
    expect(disconnected.json().data.invalidatedAt).toBeTruthy()
    expect(disconnected.json().data.reasonCategory).toBe('restricted')
    expect(disconnected.json().data.providerCode).toBe('403')
  })
})

describe('terminal connection failures', () => {
  it('preserves a restricted event instead of overwriting it with linked_offline', async () => {
    const store = new MemoryStore()
    const logger = pino({ level: 'silent' })
    const webhook = new WebhookClient('', '', 0, logger)
    const stateEvents = vi.spyOn(webhook, 'deliverAccountState')
    const service = new GatewayService(store, new TerminalConnectEngine(), webhook, logger)
    await service.start()
    await store.createAccount({ id: 'wa_terminal', phoneE164: '+14155550129', proxyUrl: 'socks5://proxy.example:1080', state: 'linked_offline' })
    await store.setCreds('wa_terminal', { registered: true })
    await store.updateAccount('wa_terminal', { deviceJid: '14155550129:1@s.whatsapp.net' })

    await expect(service.connect('wa_terminal')).rejects.toMatchObject({ code: 'protocol_error' })
    expect((await store.getAccount('wa_terminal')).state).toBe('restricted')
    expect((await store.getAccount('wa_terminal')).autoConnect).toBe(false)
    expect((await store.getAccount('wa_terminal')).invalidatedAt).toBeInstanceOf(Date)
    expect(stateEvents).toHaveBeenCalledTimes(2)
    expect(stateEvents.mock.calls[1]?.[0]).toMatchObject({
      event: 'account.state',
      accountId: 'wa_terminal',
      fromState: 'warming',
      toState: 'restricted',
      reasonCategory: 'restricted',
      providerCode: '403',
    })
    await service.disconnect('wa_terminal')
    expect(stateEvents).toHaveBeenCalledTimes(2)
    await service.close()
  })

  it('persists reauthentication-required failures as abnormal rather than offline', async () => {
    const store = new MemoryStore()
    const logger = pino({ level: 'silent' })
    const service = new GatewayService(store, new TerminalConnectEngine('reauth_required'), new WebhookClient('', '', 0, logger), logger)
    await service.start()
    await store.createAccount({ id: 'wa_reauth', phoneE164: '+14155550130', proxyUrl: 'socks5://proxy.example:1080', state: 'linked_offline' })
    await store.setCreds('wa_reauth', { registered: true })
    await store.updateAccount('wa_reauth', { deviceJid: '14155550130:1@s.whatsapp.net' })

    await expect(service.connect('wa_reauth')).rejects.toMatchObject({ code: 'protocol_error' })
    expect((await store.getAccount('wa_reauth')).state).toBe('reauth_required')
    expect((await store.getAccount('wa_reauth')).autoConnect).toBe(false)
    expect((await store.getAccount('wa_reauth')).invalidatedAt).toBeNull()
    await service.close()
  })
})

describe('account state webhook delivery', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('signs the exact payload and reuses one event id across retries', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(new Response('', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const logger = pino({ level: 'silent' })
    const secret = 'state-webhook-test-secret-at-least-32-chars'
    const occurredAt = new Date('2026-08-12T01:02:03.456Z')
    const event = {
      event: 'account.state' as const,
      eventId: 'ast_58be405d-b932-4f51-9124-cf54091158ed',
      accountId: 'wa_webhook',
      fromState: 'online_idle' as const,
      toState: 'restricted' as const,
      reasonCategory: 'restricted',
      providerCode: '403',
      occurredAt,
    }
    new WebhookClient('https://control.example/internal/events', secret, 1, logger).deliverAccountState(event)

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 2_000 })
    const first = fetchMock.mock.calls[0]!
    const second = fetchMock.mock.calls[1]!
    expect(first[1]?.body).toBe(second[1]?.body)
    const body = String(first[1]?.body)
    expect(JSON.parse(body)).toEqual({ ...event, occurredAt: occurredAt.toISOString() })
    const headers = first[1]?.headers as Record<string, string>
    expect(headers['x-parloq-event-id']).toBe(event.eventId)
    expect(headers['x-parloq-signature']).toBe(`sha256=${createHmac('sha256', secret).update(body).digest('hex')}`)
  })
})
