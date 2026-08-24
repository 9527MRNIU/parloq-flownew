import { Boom } from '@hapi/boom'
import * as BuiltinBaileys from '@whiskeysockets/baileys'
import type {
  proto,
  ConnectionState,
  WASocket,
} from '@whiskeysockets/baileys'
import type { Agent } from 'node:https'
import { createHash } from 'node:crypto'
import pino, { type Logger } from 'pino'
import { ProxyAgent } from 'proxy-agent'
import { loadAuthState, mergeCreds, type BaileysRuntimeModule } from './auth-store.js'
import type { Store } from './store.js'
import { WaWebVersionResolver } from './wa-version.js'
import type { ManagedMediaReference, MessageButton, OutboundMessage } from './message-content.js'
import type { SyncPolicy } from './domain.js'
import { classifyProxyFailure, proxyFingerprint } from './proxy-health.js'

export type EngineEvent =
  | { kind: 'connected'; accountId: string; deviceJid: string }
  | { kind: 'proxy_result'; accountId: string; outcome: 'success' | 'failure'; reasonCategory: string; proxyFingerprint: string }
  | { kind: 'pairing_restarting'; accountId: string; reasonCategory: string; providerCode?: string }
  | { kind: 'disconnected' | 'logged_out' | 'reauth_required' | 'restricted'; accountId: string; reasonCategory: string; providerCode?: string }
  | { kind: 'delivered'; accountId: string; providerMessageId: string }

export interface PairResult { accountId: string; code: string; expiresAt: Date; deviceJid?: string }
export interface EngineAccount {
  accountId: string
  protocolDefinitionId: string
  protocolVersion: string
  phoneE164: string
  proxyUrl: string
  syncPolicy: SyncPolicy
}
export interface AccountQuality {
  hasAvatar: boolean | null
  groupCount: number | null
  friendCount: number | null
  mutualContactCount: number | null
  metadata: Record<string, unknown>
}

export interface ProtocolVersionInfo {
  currentWaWebVersion: string | null
  latestWaWebVersion: string | null
  versionStatus: 'current' | 'update_available' | 'stale' | 'fallback' | 'unavailable'
  checkedAt: string | null
  checkError: string | null
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
  send(accountId: string, toE164: string, message: OutboundMessage): Promise<string>
  getQuality(accountId: string, policy: SyncPolicy): Promise<AccountQuality>
  isOnline(accountId: string): boolean
  setEventHandler(handler: (event: EngineEvent) => void): void
  protocolVersionInfo?(): Promise<ProtocolVersionInfo>
}

interface ActiveSocket {
  socket: WASocket
  online: boolean
  proxyAgent?: ProxyAgent
  proxyFailureReported?: boolean
}

interface PairingEventEmitter {
  on(event: 'connection.update', listener: (update: Partial<ConnectionState>) => void): unknown
  off(event: 'connection.update', listener: (update: Partial<ConnectionState>) => void): unknown
}

type PairingSocket = Pick<WASocket, 'requestPairingCode'> & {
  ev: PairingEventEmitter
}

interface ReconnectableCredentials {
  registered?: boolean
  me?: { id?: string } | null
  account?: unknown
}

export function hasReconnectableIdentity(creds: ReconnectableCredentials): boolean {
  return creds.registered === true || Boolean(creds.me?.id && creds.account)
}

export function isRequiredPairingRestart(
  statusCode: number,
  pairingConfigured: boolean,
  creds: ReconnectableCredentials,
  restartRequired = BuiltinBaileys.DisconnectReason.restartRequired,
): boolean {
  return statusCode === restartRequired
    && pairingConfigured
    && hasReconnectableIdentity(creds)
}

export function nativeFlowButton(button: MessageButton): { name: string; buttonParamsJson: string } {
  if (button.type === 'quick_reply') {
    return {
      name: 'quick_reply',
      buttonParamsJson: JSON.stringify({ display_text: button.text, id: button.id }),
    }
  }
  if (button.type === 'url') {
    return {
      name: 'cta_url',
      buttonParamsJson: JSON.stringify({ display_text: button.text, url: button.url, merchant_url: button.url }),
    }
  }
  if (button.type === 'call') {
    return {
      name: 'cta_call',
      buttonParamsJson: JSON.stringify({ display_text: button.text, phone_number: `+${button.phone}` }),
    }
  }
  if (button.type === 'copy') {
    return {
      name: 'cta_copy',
      buttonParamsJson: JSON.stringify({ display_text: button.text, id: `copy_${button.copyText}`, copy_code: button.copyText }),
    }
  }
  return {
    name: 'single_select',
    buttonParamsJson: JSON.stringify({ title: button.text, sections: button.sections }),
  }
}

export async function requestStablePairingCode(
  socket: PairingSocket,
  phone: string,
  readyTimeoutMs = 20_000,
  stabilityMs = 250,
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
  private readonly syncSnapshots = new Map<string, Record<string, unknown>>()
  private handler: (event: EngineEvent) => void = () => undefined
  private started = false
  private readonly protocolLogger: Logger
  private readonly versionResolver: WaWebVersionResolver
  private currentWaWebVersion: string | null = null

  constructor(
    private readonly store: Store,
    logger?: Logger,
    private readonly materialBaseUrl = 'http://api:8000',
    private readonly baileys: BaileysRuntimeModule = BuiltinBaileys,
  ) {
    this.protocolLogger = (logger ?? pino({ level: 'warn' })).child({ component: 'baileys' })
    this.versionResolver = new WaWebVersionResolver(
      this.protocolLogger,
      this.baileys.fetchLatestWaWebVersion,
    )
  }

  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> { this.started = true }
  async ready(): Promise<void> { if (!this.started) throw new Error('Baileys engine is not started') }
  isOnline(accountId: string): boolean { return this.sockets.get(accountId)?.online === true }

  async protocolVersionInfo(): Promise<ProtocolVersionInfo> {
    try {
      const status = await this.versionResolver.inspect()
      const latest = status.latestVersion?.join('.') ?? null
      const current = this.currentWaWebVersion ?? status.resolvedVersion.join('.')
      return {
        currentWaWebVersion: current,
        latestWaWebVersion: latest,
        versionStatus: status.resolution === 'stale'
          ? 'stale'
          : status.resolution === 'fallback'
            ? 'fallback'
            : latest && current !== latest
              ? 'update_available'
              : 'current',
        checkedAt: status.checkedAt,
        checkError: status.error,
      }
    } catch (error) {
      return {
        currentWaWebVersion: this.currentWaWebVersion,
        latestWaWebVersion: null,
        versionStatus: 'unavailable',
        checkedAt: new Date().toISOString(),
        checkError: error instanceof Error ? error.message : String(error),
      }
    }
  }

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
        this.reportProxyFailure(account, active, new Error('timed out waiting for proxy connection'))
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

  private async fetchManagedMaterial(media: ManagedMediaReference): Promise<Buffer> {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 45_000)
    timeout.unref()
    try {
      const response = await fetch(
        `${this.materialBaseUrl}/api/internal/materials/${media.id}/content`,
        {
          headers: { Authorization: `Bearer ${media.token}` },
          signal: controller.signal,
        },
      )
      if (!response.ok) throw new Error(`managed material fetch failed (${response.status})`)
      const declared = Number(response.headers.get('content-length') || 0)
      if (declared && declared !== media.size) throw new Error('managed material size changed')
      const content = Buffer.from(await response.arrayBuffer())
      if (content.length !== media.size || content.length > 64 * 1024 * 1024) {
        throw new Error('managed material size is invalid')
      }
      const digest = createHash('sha256').update(content).digest('hex')
      if (digest !== media.sha256) throw new Error('managed material checksum changed')
      return content
    } finally {
      clearTimeout(timeout)
    }
  }

  async send(accountId: string, toE164: string, message: OutboundMessage): Promise<string> {
    const active = this.sockets.get(accountId)
    if (!active?.online) throw new Error('account is offline')
    const jid = `${toE164.slice(1)}@s.whatsapp.net`
    let id: string | null | undefined
    if (!message.buttons.length) {
      const footer = message.footer.text
      if (message.header.type === 'image') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const result = await active.socket.sendMessage(jid, {
          image: content,
          mimetype: message.header.media.mimeType,
          caption: [message.body.text, footer].filter(Boolean).join('\n\n'),
        })
        id = result?.key.id
      } else if (message.header.type === 'video') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const result = await active.socket.sendMessage(jid, {
          video: content,
          mimetype: message.header.media.mimeType,
          caption: [message.body.text, footer].filter(Boolean).join('\n\n'),
        })
        id = result?.key.id
      } else if (message.header.type === 'document') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const result = await active.socket.sendMessage(jid, {
          document: content,
          fileName: message.header.media.fileName,
          mimetype: message.header.media.mimeType,
          caption: [message.body.text, footer].filter(Boolean).join('\n\n'),
        })
        id = result?.key.id
      } else {
        const result = await active.socket.sendMessage(jid, {
          text: [message.header.type === 'text' ? message.header.text : '', message.body.text, footer]
            .filter(Boolean)
            .join('\n\n'),
        })
        id = result?.key.id
      }
    } else {
      const userJid = active.socket.user?.id
      if (!userJid) throw new Error('account user identity is unavailable')
      const header: proto.Message.InteractiveMessage.IHeader = {
        hasMediaAttachment: false,
      }
      if (message.header.type === 'text') header.title = message.header.text
      if (message.header.type === 'image') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const media = await this.baileys.prepareWAMessageMedia(
          { image: content },
          { upload: active.socket.waUploadToServer },
        )
        header.hasMediaAttachment = true
        if (!media.imageMessage) throw new Error('provider did not prepare the image header')
        header.imageMessage = media.imageMessage
      } else if (message.header.type === 'video') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const media = await this.baileys.prepareWAMessageMedia(
          { video: content },
          { upload: active.socket.waUploadToServer },
        )
        header.hasMediaAttachment = true
        if (!media.videoMessage) throw new Error('provider did not prepare the video header')
        header.videoMessage = media.videoMessage
      } else if (message.header.type === 'document') {
        const content = await this.fetchManagedMaterial(message.header.media)
        const media = await this.baileys.prepareWAMessageMedia(
          {
            document: content,
            fileName: message.header.media.fileName,
            mimetype: message.header.media.mimeType,
          },
          { upload: active.socket.waUploadToServer },
        )
        header.hasMediaAttachment = true
        if (!media.documentMessage) throw new Error('provider did not prepare the document header')
        header.documentMessage = media.documentMessage
      }
      const interactiveMessage = this.baileys.proto.Message.InteractiveMessage.fromObject({
        header,
        body: { text: message.body.text },
        footer: { text: message.footer.text },
        nativeFlowMessage: {
          buttons: message.buttons.map(nativeFlowButton),
          messageParamsJson: '',
          messageVersion: 1,
        },
      })
      const generated = this.baileys.generateWAMessageFromContent(
        jid,
        {
          viewOnceMessage: {
            message: {
              messageContextInfo: {
                deviceListMetadata: {},
                deviceListMetadataVersion: 2,
              },
              interactiveMessage,
            },
          },
        },
        { userJid },
      )
      id = generated.key.id
      if (!id || !generated.message) throw new Error('provider did not generate an interactive message id')
      await active.socket.relayMessage(jid, generated.message, { messageId: id })
    }
    if (!id) throw new Error('provider did not return a message id')
    return id
  }

  async getQuality(accountId: string, policy: SyncPolicy): Promise<AccountQuality> {
    const active = this.sockets.get(accountId)
    if (!active?.online) throw new Error('account is offline')
    const ownJid = active.socket.user?.id
    let hasAvatar: boolean | null = null
    if (policy.avatar && ownJid) {
      try {
        hasAvatar = Boolean(await active.socket.profilePictureUrl(ownJid, 'preview'))
      } catch (error) {
        const statusCode = new Boom(error instanceof Error ? error : String(error)).output.statusCode
        if (statusCode === 404) hasAvatar = false
      }
    }
    let groupCount: number | null = null
    const metadata: Record<string, unknown> = { ...(this.syncSnapshots.get(accountId) ?? {}) }
    if (policy.groupSummary || policy.groupDetails) {
      try {
        const groups = await active.socket.groupFetchAllParticipating()
        groupCount = Object.keys(groups).length
        if (policy.groupDetails) {
          metadata.groups = Object.values(groups).map((group) => ({
            id: group.id,
            subject: group.subject,
            size: group.size,
          }))
        }
      } catch {
        groupCount = null
      }
    }
    if (ownJid && policy.profileStatus) {
      try { metadata.profileStatus = await active.socket.fetchStatus(ownJid) } catch { metadata.profileStatusError = 'unavailable' }
    }
    if (ownJid && policy.businessProfile) {
      try { metadata.businessProfile = await active.socket.getBusinessProfile(ownJid) } catch { metadata.businessProfileError = 'unavailable' }
    }
    if (policy.privacySettings) {
      try { metadata.privacySettings = await active.socket.fetchPrivacySettings() } catch { metadata.privacySettingsError = 'unavailable' }
    }
    if (policy.blocklist) {
      try { metadata.blocklist = await active.socket.fetchBlocklist() } catch { metadata.blocklistError = 'unavailable' }
    }
    // Baileys does not expose a stable, privacy-safe definition for “friends”
    // or “mutual contacts” without syncing chat/contact history. Keep them
    // unknown instead of manufacturing zeroes.
    return { hasAvatar, groupCount, friendCount: null, mutualContactCount: null, metadata }
  }

  private async openSocket(account: EngineAccount, createAuth: boolean): Promise<ActiveSocket> {
    this.blockedReconnect.delete(account.accountId)
    const existing = this.sockets.get(account.accountId)
    if (existing) return existing
    const { state, saveCreds } = await loadAuthState(this.store, account.accountId, createAuth, this.baileys)
    const proxyAgent = account.proxyUrl
      ? new ProxyAgent({ getProxyForUrl: () => account.proxyUrl })
      : undefined
    let version
    try {
      version = await this.versionResolver.current(proxyAgent as Agent | undefined, createAuth)
      this.currentWaWebVersion = version.join('.')
    } catch (error) {
      this.reportProxyFailure(account, undefined, error)
      proxyAgent?.destroy()
      throw error
    }
    const socket = this.baileys.default({
      auth: state,
      browser: this.baileys.Browsers.macOS('Chrome'),
      version,
      logger: this.protocolLogger,
      markOnlineOnConnect: false,
      syncFullHistory: account.syncPolicy.contacts || account.syncPolicy.chats || account.syncPolicy.messageHistory,
      shouldSyncHistoryMessage: () => account.syncPolicy.messageHistory,
      ...(proxyAgent ? { agent: proxyAgent as Agent, fetchAgent: proxyAgent as Agent } : {}),
    })
    const active: ActiveSocket = proxyAgent ? { socket, online: false, proxyAgent } : { socket, online: false }
    this.sockets.set(account.accountId, active)
    this.syncSnapshots.set(account.accountId, {})

    let credsSaveTail = Promise.resolve()
    let pairingConfigured = false
    socket.ev.on('creds.update', (update) => {
      mergeCreds(state.creds, update)
      credsSaveTail = credsSaveTail.catch(() => undefined).then(saveCreds)
      void credsSaveTail.catch((error: unknown) => {
        this.protocolLogger.error({ accountId: account.accountId, error }, 'credential_persist_failed')
      })
    })
    socket.ev.on('connection.update', (update) => {
      if (update.isNewLogin === true) pairingConfigured = true
      if (update.connection === 'open') {
        active.online = true
        active.proxyFailureReported = false
        this.reconnectAttempts.delete(account.accountId)
        if (account.proxyUrl) {
          this.handler({
            kind: 'proxy_result',
            accountId: account.accountId,
            outcome: 'success',
            reasonCategory: 'proxy_connected',
            proxyFingerprint: proxyFingerprint(account.proxyUrl),
          })
        }
        const deviceJid = socket.user?.id ?? state.creds.me?.id ?? ''
        this.handler({ kind: 'connected', accountId: account.accountId, deviceJid })
      } else if (update.connection === 'close') {
        active.online = false
        if (this.sockets.get(account.accountId) === active) this.sockets.delete(account.accountId)
        proxyAgent?.destroy()
        const disconnectError = update.lastDisconnect?.error
        this.reportProxyFailure(account, active, disconnectError)
        const statusCode = disconnectError instanceof Boom
          ? disconnectError.output.statusCode
          : new Boom(disconnectError).output.statusCode
        const providerCode = String(statusCode)
        if (statusCode === this.baileys.DisconnectReason.loggedOut) {
          void this.store.clearAuth(account.accountId)
          this.handler({ kind: 'logged_out', accountId: account.accountId, reasonCategory: 'logged_out', providerCode })
        } else if (statusCode === this.baileys.DisconnectReason.forbidden) {
          this.handler({ kind: 'restricted', accountId: account.accountId, reasonCategory: 'restricted', providerCode })
        } else if ([this.baileys.DisconnectReason.badSession, this.baileys.DisconnectReason.multideviceMismatch].includes(statusCode)) {
          this.handler({
            kind: 'reauth_required',
            accountId: account.accountId,
            reasonCategory: statusCode === this.baileys.DisconnectReason.badSession ? 'bad_session' : 'multidevice_mismatch',
            providerCode,
          })
        } else {
          const transient = [
            this.baileys.DisconnectReason.restartRequired,
            this.baileys.DisconnectReason.connectionLost,
            this.baileys.DisconnectReason.connectionClosed,
            this.baileys.DisconnectReason.timedOut,
            this.baileys.DisconnectReason.unavailableService,
          ].includes(statusCode)
          const hasLinkedIdentity = hasReconnectableIdentity(state.creds)
          const pairingRestart = isRequiredPairingRestart(
            statusCode,
            pairingConfigured,
            state.creds,
            this.baileys.DisconnectReason.restartRequired,
          )
          if (pairingRestart && !this.blockedReconnect.has(account.accountId)) {
            // A 515 immediately after pair-success is the normal second half
            // of Baileys device linking. WhatsApp expects a fresh socket using
            // the credentials emitted by pair-success. Treating this as an
            // interrupted pairing clears the new identity and makes the phone
            // wait until it reports that the device could not be linked.
            this.handler({
              kind: 'pairing_restarting',
              accountId: account.accountId,
              reasonCategory: 'pairing_restart_required',
              providerCode,
            })
          } else if (!this.blockedReconnect.has(account.accountId)) {
            this.handler({
              kind: 'disconnected',
              accountId: account.accountId,
              reasonCategory: transient ? 'connection_lost' : 'protocol_disconnect',
              providerCode,
            })
          }
          // Temporary code-only auth is not reconnectable: reopening it does
          // not re-submit the companion registration request. A registered
          // session or the identity returned by pair-success is reconnectable.
          if (transient && hasLinkedIdentity) {
            // Pair-success credentials are persisted asynchronously by
            // Baileys. Never open the replacement socket before that write is
            // complete, otherwise the restart can load the pre-pairing state.
            void credsSaveTail.then(
              () => this.scheduleReconnect(account),
              () => this.handler({
                kind: 'disconnected',
                accountId: account.accountId,
                reasonCategory: 'credential_store_failure',
                providerCode,
              }),
            )
          }
        }
      }
    })
    socket.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
      const snapshot = this.syncSnapshots.get(account.accountId) ?? {}
      if (account.syncPolicy.chats) snapshot.chatCount = chats.length
      if (account.syncPolicy.contacts) snapshot.contactCount = contacts.length
      if (account.syncPolicy.messageHistory) snapshot.historyMessageCount = messages.length
      this.syncSnapshots.set(account.accountId, snapshot)
    })
    socket.ev.on('contacts.upsert', (contacts) => {
      if (!account.syncPolicy.contacts) return
      const snapshot = this.syncSnapshots.get(account.accountId) ?? {}
      snapshot.contactUpdateCount = Number(snapshot.contactUpdateCount ?? 0) + contacts.length
      this.syncSnapshots.set(account.accountId, snapshot)
    })
    socket.ev.on('messages.update', (updates) => {
      for (const update of updates) {
        const id = update.key.id
        const status = update.update.status
        if (id && status != null && status >= this.baileys.WAMessageStatus.DELIVERY_ACK) {
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

  private reportProxyFailure(
    account: EngineAccount,
    active: ActiveSocket | undefined,
    error: unknown,
  ): void {
    if (!account.proxyUrl || active?.proxyFailureReported) return
    const reasonCategory = classifyProxyFailure(error)
    if (!reasonCategory) return
    if (active) active.proxyFailureReported = true
    this.handler({
      kind: 'proxy_result',
      accountId: account.accountId,
      outcome: 'failure',
      reasonCategory,
      proxyFingerprint: proxyFingerprint(account.proxyUrl),
    })
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
  async send(id: string, _to: string, _message: OutboundMessage): Promise<string> {
    if (!this.isOnline(id)) throw new Error('account is offline')
    return `mock-${crypto.randomUUID()}`
  }
  async getQuality(_id: string, _policy: SyncPolicy): Promise<AccountQuality> {
    return { hasAvatar: null, groupCount: null, friendCount: null, mutualContactCount: null, metadata: {} }
  }
}
