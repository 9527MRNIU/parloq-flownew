import { Boom } from '@hapi/boom'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  WAMessageStatus,
  type ConnectionState,
  type WASocket,
} from '@whiskeysockets/baileys'
import type { Agent } from 'node:https'
import pino, { type Logger } from 'pino'
import { ProxyAgent } from 'proxy-agent'
import { loadAuthState, mergeCreds } from './auth-store.js'
import type { Store } from './store.js'
import { WaWebVersionResolver } from './wa-version.js'

export type EngineEvent =
  | { kind: 'connected'; accountId: string; deviceJid: string }
  | { kind: 'disconnected' | 'logged_out' | 'reauth_required' | 'restricted'; accountId: string; reasonCategory: string; providerCode?: string }
  | { kind: 'delivered'; accountId: string; providerMessageId: string }

export interface PairResult { accountId: string; code: string; expiresAt: Date; deviceJid?: string }
export interface EngineAccount { accountId: string; phoneE164: string; proxyUrl: string }
export interface AccountQuality {
  hasAvatar: boolean | null
  groupCount: number | null
  friendCount: number | null
  mutualContactCount: number | null
}

export interface ProtocolEngine {
  readonly name: string
  start(): Promise<void>
  ready(): Promise<void>
  close(): Promise<void>
  pair(account: EngineAccount): Promise<PairResult>
  connect(account: EngineAccount): Promise<void>
  disconnect(accountId: string): Promise<void>
  logout(account: EngineAccount): Promise<void>
  send(accountId: string, toE164: string, text: string): Promise<string>
  getQuality(accountId: string): Promise<AccountQuality>
  isOnline(accountId: string): boolean
  setEventHandler(handler: (event: EngineEvent) => void): void
}

interface ActiveSocket {
  socket: WASocket
  online: boolean
  proxyAgent?: ProxyAgent
}

interface PairingEventEmitter {
  on(event: 'connection.update', listener: (update: Partial<ConnectionState>) => void): unknown
  off(event: 'connection.update', listener: (update: Partial<ConnectionState>) => void): unknown
}

type PairingSocket = Pick<WASocket, 'requestPairingCode'> & {
  ev: PairingEventEmitter
}

export async function requestStablePairingCode(
  socket: PairingSocket,
  phone: string,
  readyTimeoutMs = 20_000,
  stabilityMs = 6_000,
): Promise<string> {
  let resolveReady: (() => void) | undefined
  let rejectClosed: ((reason?: unknown) => void) | undefined
  let readyTimer: ReturnType<typeof setTimeout> | undefined
  const ready = new Promise<void>((resolve) => { resolveReady = resolve })
  const closed = new Promise<never>((_resolve, reject) => { rejectClosed = reject })
  const listener = (update: Partial<ConnectionState>) => {
    // Baileys emits the first QR only after the unregistered registration
    // handshake has completed and WhatsApp has returned pair-device refs.
    // A raw websocket-open event is too early: requestPairingCode() writes
    // creds.me, which can race validateConnection() and make a new account
    // send a login node instead of a registration node.
    if (typeof update.qr === 'string' && update.qr.length > 0) resolveReady?.()
    if (update.connection === 'close') {
      rejectClosed?.(update.lastDisconnect?.error ?? new Error('pairing socket closed'))
    }
  }
  socket.ev.on('connection.update', listener)
  try {
    await Promise.race([
      ready,
      closed,
      new Promise<never>((_resolve, reject) => {
        readyTimer = setTimeout(
          () => reject(new Error('timed out waiting for WhatsApp pairing registration')),
          readyTimeoutMs,
        )
        readyTimer.unref()
      }),
    ])
    if (readyTimer) clearTimeout(readyTimer)
    const code = await Promise.race([
      socket.requestPairingCode(phone),
      closed,
    ])
    await Promise.race([
      new Promise<void>((resolve) => setTimeout(resolve, stabilityMs)),
      closed,
    ])
    return code
  } finally {
    if (readyTimer) clearTimeout(readyTimer)
    socket.ev.off('connection.update', listener)
  }
}

export class BaileysEngine implements ProtocolEngine {
  readonly name = 'baileys'
  private readonly sockets = new Map<string, ActiveSocket>()
  private readonly reconnectAttempts = new Map<string, number>()
  private readonly blockedReconnect = new Set<string>()
  private handler: (event: EngineEvent) => void = () => undefined
  private started = false
  private readonly protocolLogger: Logger
  private readonly versionResolver: WaWebVersionResolver

  constructor(private readonly store: Store, logger?: Logger) {
    this.protocolLogger = (logger ?? pino({ level: 'warn' })).child({ component: 'baileys' })
    this.versionResolver = new WaWebVersionResolver(this.protocolLogger)
  }

  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> { this.started = true }
  async ready(): Promise<void> { if (!this.started) throw new Error('Baileys engine is not started') }
  isOnline(accountId: string): boolean { return this.sockets.get(accountId)?.online === true }

  async close(): Promise<void> {
    for (const accountId of [...this.sockets.keys()]) await this.disconnect(accountId)
    this.started = false
  }

  async pair(account: EngineAccount): Promise<PairResult> {
    const active = await this.openSocket(account, true)
    const phone = account.phoneE164.slice(1)
    const issuedAt = Date.now()
    const code = await requestStablePairingCode(active.socket, phone)
    return { accountId: account.accountId, code, expiresAt: new Date(issuedAt + 3 * 60_000) }
  }

  async connect(account: EngineAccount): Promise<void> {
    if (this.isOnline(account.accountId)) return
    const active = await this.openSocket(account, false)
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        active.socket.ev.off('connection.update', listener)
        reject(new Error('timed out waiting for Baileys connection'))
      }, 45_000)
      const listener = (update: Partial<ConnectionState>) => {
        if (update.connection === 'open') {
          clearTimeout(timer)
          active.socket.ev.off('connection.update', listener)
          resolve()
        } else if (update.connection === 'close') {
          clearTimeout(timer)
          active.socket.ev.off('connection.update', listener)
          reject(update.lastDisconnect?.error ?? new Error('Baileys connection closed'))
        }
      }
      active.socket.ev.on('connection.update', listener)
      if (active.online) {
        clearTimeout(timer)
        active.socket.ev.off('connection.update', listener)
        resolve()
      }
    })
  }

  async disconnect(accountId: string): Promise<void> {
    this.blockedReconnect.add(accountId)
    const active = this.sockets.get(accountId)
    if (!active) return
    this.sockets.delete(accountId)
    active.socket.end(new Error('gateway disconnect'))
    active.proxyAgent?.destroy()
  }

  async logout(account: EngineAccount): Promise<void> {
    if (!this.sockets.has(account.accountId)) await this.connect(account)
    this.blockedReconnect.add(account.accountId)
    const active = this.sockets.get(account.accountId)
    if (!active) throw new Error('account socket is unavailable')
    await active.socket.logout()
    this.sockets.delete(account.accountId)
    active.proxyAgent?.destroy()
    await this.store.clearAuth(account.accountId)
  }

  async send(accountId: string, toE164: string, text: string): Promise<string> {
    const active = this.sockets.get(accountId)
    if (!active?.online) throw new Error('account is offline')
    const jid = `${toE164.slice(1)}@s.whatsapp.net`
    const result = await active.socket.sendMessage(jid, { text })
    const id = result?.key.id
    if (!id) throw new Error('provider did not return a message id')
    return id
  }

  async getQuality(accountId: string): Promise<AccountQuality> {
    const active = this.sockets.get(accountId)
    if (!active?.online) throw new Error('account is offline')
    const ownJid = active.socket.user?.id
    let hasAvatar: boolean | null = null
    if (ownJid) {
      try {
        hasAvatar = Boolean(await active.socket.profilePictureUrl(ownJid, 'preview'))
      } catch (error) {
        const statusCode = new Boom(error instanceof Error ? error : String(error)).output.statusCode
        if (statusCode === 404) hasAvatar = false
      }
    }
    let groupCount: number | null = null
    try {
      groupCount = Object.keys(await active.socket.groupFetchAllParticipating()).length
    } catch {
      groupCount = null
    }
    // Baileys does not expose a stable, privacy-safe definition for “friends”
    // or “mutual contacts” without syncing chat/contact history. Keep them
    // unknown instead of manufacturing zeroes.
    return { hasAvatar, groupCount, friendCount: null, mutualContactCount: null }
  }

  private async openSocket(account: EngineAccount, createAuth: boolean): Promise<ActiveSocket> {
    this.blockedReconnect.delete(account.accountId)
    const existing = this.sockets.get(account.accountId)
    if (existing) return existing
    const { state, saveCreds } = await loadAuthState(this.store, account.accountId, createAuth)
    const proxyAgent = account.proxyUrl
      ? new ProxyAgent({ getProxyForUrl: () => account.proxyUrl })
      : undefined
    let version
    try {
      version = await this.versionResolver.current(proxyAgent as Agent | undefined, createAuth)
    } catch (error) {
      proxyAgent?.destroy()
      throw error
    }
    const socket = makeWASocket({
      auth: state,
      browser: Browsers.macOS('Chrome'),
      version,
      logger: this.protocolLogger,
      markOnlineOnConnect: true,
      syncFullHistory: false,
      shouldSyncHistoryMessage: () => false,
      ...(proxyAgent ? { agent: proxyAgent as Agent, fetchAgent: proxyAgent as Agent } : {}),
    })
    const active: ActiveSocket = proxyAgent ? { socket, online: false, proxyAgent } : { socket, online: false }
    this.sockets.set(account.accountId, active)

    socket.ev.on('creds.update', async (update) => {
      mergeCreds(state.creds, update)
      await saveCreds()
    })
    socket.ev.on('connection.update', (update) => {
      if (update.connection === 'open') {
        active.online = true
        this.reconnectAttempts.delete(account.accountId)
        const deviceJid = socket.user?.id ?? state.creds.me?.id ?? ''
        this.handler({ kind: 'connected', accountId: account.accountId, deviceJid })
      } else if (update.connection === 'close') {
        active.online = false
        if (this.sockets.get(account.accountId) === active) this.sockets.delete(account.accountId)
        proxyAgent?.destroy()
        const disconnectError = update.lastDisconnect?.error
        const statusCode = disconnectError instanceof Boom
          ? disconnectError.output.statusCode
          : new Boom(disconnectError).output.statusCode
        const providerCode = String(statusCode)
        if (statusCode === DisconnectReason.loggedOut) {
          void this.store.clearAuth(account.accountId)
          this.handler({ kind: 'logged_out', accountId: account.accountId, reasonCategory: 'logged_out', providerCode })
        } else if (statusCode === DisconnectReason.forbidden) {
          this.handler({ kind: 'restricted', accountId: account.accountId, reasonCategory: 'restricted', providerCode })
        } else if ([DisconnectReason.badSession, DisconnectReason.multideviceMismatch].includes(statusCode)) {
          this.handler({
            kind: 'reauth_required',
            accountId: account.accountId,
            reasonCategory: statusCode === DisconnectReason.badSession ? 'bad_session' : 'multidevice_mismatch',
            providerCode,
          })
        } else {
          const transient = [
            DisconnectReason.restartRequired,
            DisconnectReason.connectionLost,
            DisconnectReason.connectionClosed,
            DisconnectReason.timedOut,
            DisconnectReason.unavailableService,
          ].includes(statusCode)
          if (!this.blockedReconnect.has(account.accountId)) {
            this.handler({
              kind: 'disconnected',
              accountId: account.accountId,
              reasonCategory: transient ? 'connection_lost' : 'protocol_disconnect',
              providerCode,
            })
          }
          // Only registered sessions are reconnectable. A pairing code is
          // bound to the unregistered socket that requested it; reopening a
          // socket with those temporary credentials does not re-submit the
          // companion registration request and makes the displayed code stale.
          if (transient && state.creds.registered) {
            this.scheduleReconnect(account)
          }
        }
      }
    })
    socket.ev.on('messages.update', (updates) => {
      for (const update of updates) {
        const id = update.key.id
        const status = update.update.status
        if (id && status != null && status >= WAMessageStatus.DELIVERY_ACK) {
          this.handler({ kind: 'delivered', accountId: account.accountId, providerMessageId: id })
        }
      }
    })
    return active
  }

  private scheduleReconnect(account: EngineAccount): void {
    if (!this.started || this.blockedReconnect.has(account.accountId)) return
    const attempt = (this.reconnectAttempts.get(account.accountId) ?? 0) + 1
    this.reconnectAttempts.set(account.accountId, attempt)
    const delay = Math.min(30_000, 500 * 2 ** Math.min(attempt - 1, 6))
    setTimeout(() => {
      if (!this.started || this.blockedReconnect.has(account.accountId) || this.sockets.has(account.accountId)) return
      void this.openSocket(account, false).catch(() => this.scheduleReconnect(account))
    }, delay).unref()
  }
}

interface MockState { linked: boolean; online: boolean }

export class MockEngine implements ProtocolEngine {
  readonly name = 'mock'
  private readonly accounts = new Map<string, MockState>()
  private handler: (event: EngineEvent) => void = () => undefined
  private started = false
  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> { this.started = true }
  async ready(): Promise<void> { if (!this.started) throw new Error('mock engine is not started') }
  async close(): Promise<void> { this.accounts.clear(); this.started = false }
  isOnline(id: string): boolean { return this.accounts.get(id)?.online === true }
  async pair(account: EngineAccount): Promise<PairResult> {
    this.accounts.set(account.accountId, { linked: true, online: true })
    queueMicrotask(() => this.handler({ kind: 'connected', accountId: account.accountId, deviceJid: `mock-${account.accountId}@s.whatsapp.net` }))
    return { accountId: account.accountId, code: '0000-0000', expiresAt: new Date(Date.now() + 180_000), deviceJid: `mock-${account.accountId}@s.whatsapp.net` }
  }
  async connect(account: EngineAccount): Promise<void> {
    const current = this.accounts.get(account.accountId) ?? { linked: true, online: false }
    current.online = true
    this.accounts.set(account.accountId, current)
    this.handler({ kind: 'connected', accountId: account.accountId, deviceJid: `mock-${account.accountId}@s.whatsapp.net` })
  }
  async disconnect(id: string): Promise<void> { const state = this.accounts.get(id); if (state) state.online = false }
  async logout(account: EngineAccount): Promise<void> { this.accounts.delete(account.accountId); this.handler({ kind: 'logged_out', accountId: account.accountId, reasonCategory: 'logged_out' }) }
  async send(id: string, _to: string, _text: string): Promise<string> {
    if (!this.isOnline(id)) throw new Error('account is offline')
    return `mock-${crypto.randomUUID()}`
  }
  async getQuality(_id: string): Promise<AccountQuality> {
    return { hasAvatar: null, groupCount: null, friendCount: null, mutualContactCount: null }
  }
}
