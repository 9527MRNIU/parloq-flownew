import type { Logger } from 'pino'
import type { Account, AccountState, Message, PublicAccount } from './domain.js'
import { GatewayError, normalizeE164, publicAccount, safeError, validateProxy } from './domain.js'
import type { EngineEvent, PairResult, ProtocolEngine } from './engine.js'
import { exportSession, parseImportedSession, phoneFromDeviceJid } from './session.js'
import type { Store } from './store.js'
import { newPublicId } from './snowflake.js'
import { WebhookClient } from './webhook.js'

export interface CreateAccountRequest { id?: string; phoneE164: string; proxyUrl?: string }
export interface UpdateAccountRequest { phoneE164?: string; proxyUrl?: string; autoConnect?: boolean }
export interface SendTextRequest { messageId: string; toE164: string; text: string }

function pairingCodeFromCreds(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const code = (value as { pairingCode?: unknown }).pairingCode
  return typeof code === 'string' && /^[A-Z0-9]{8}$/i.test(code) ? code : null
}

export class GatewayService {
  private readonly queueDepth = new Map<string, number>()
  private readonly queueTail = new Map<string, Promise<void>>()
  private readonly nextSendAt = new Map<string, number>()
  private readonly pendingEngineEvents = new Map<string, Promise<void>>()
  private readonly pairingExpiryTimers = new Map<string, ReturnType<typeof setTimeout>>()

  constructor(
    private readonly store: Store,
    private readonly engine: ProtocolEngine,
    private readonly webhook: WebhookClient,
    private readonly logger: Logger,
    private readonly maxQueueSize = 1_000,
    private readonly sendQps = 10,
  ) {
    engine.setEventHandler((event) => {
      const previous = this.pendingEngineEvents.get(event.accountId) ?? Promise.resolve()
      const pending = previous.then(() => this.handleEngineEvent(event))
      this.pendingEngineEvents.set(event.accountId, pending)
      void pending.finally(() => {
        if (this.pendingEngineEvents.get(event.accountId) === pending) {
          this.pendingEngineEvents.delete(event.accountId)
        }
      })
    })
  }

  get engineName(): string { return this.engine.name }

  async start(): Promise<void> {
    await this.store.migrate()
    await this.engine.start()
    const accounts = await this.store.listAccounts()
    for (const account of accounts.filter((item) => item.state === 'pairing' && ['waiting_phone', 'reconnecting'].includes(item.pairingStatus))) {
      if (!account.pairingExpiresAt || account.pairingExpiresAt.getTime() <= Date.now()) {
        await this.expirePairing(account.id)
        continue
      }
      // A phone pairing code belongs to the socket that issued it. If the
      // gateway restarted, that socket no longer exists and the old code must
      // not be restored or shown as usable.
      await this.store.clearAuth(account.id)
      await this.transitionAccount(account.id, 'unpaired', {
        deviceJid: '',
        autoConnect: false,
        sessionStatus: 'none',
        sessionCompleteness: 'none',
        pairingStatus: 'failed',
        pairingExpiresAt: null,
      }, 'pairing_interrupted')
    }
    for (const account of accounts.filter((item) => item.autoConnect && item.deviceJid)) {
      void this.connect(account.id).catch((error: unknown) => this.logger.warn({ accountId: account.id, error: safeError(error) }, 'account_restore_failed'))
    }
  }

  async close(): Promise<void> {
    for (const timer of this.pairingExpiryTimers.values()) clearTimeout(timer)
    this.pairingExpiryTimers.clear()
    await this.engine.close()
    await this.store.close()
  }
  async ready(): Promise<void> { await this.store.ready(); await this.engine.ready() }

  async createAccount(request: CreateAccountRequest): Promise<PublicAccount> {
    const phoneE164 = normalizeE164(request.phoneE164)
    const proxyUrl = validateProxy(request.proxyUrl ?? '')
    const id = request.id?.trim() || newPublicId('wa')
    if (!/^[A-Za-z0-9_.-]{1,80}$/.test(id)) throw new GatewayError('invalid_argument', 'account id contains unsupported characters')
    try {
      return publicAccount(await this.store.createAccount({ id, phoneE164, proxyUrl, state: 'unpaired' }))
    } catch (error) {
      if (!(error instanceof GatewayError) || error.code !== 'conflict') throw error
      // A control-plane transaction may fail after the gateway account was
      // created. Reclaim only a credential-free, unused row for the exact
      // phone so a later landing-page retry is not permanently blocked.
      const reclaimed = await this.store.claimUnpairedAccount({ id, phoneE164, proxyUrl })
      if (!reclaimed) throw error
      return publicAccount(reclaimed)
    }
  }

  async listAccounts(): Promise<PublicAccount[]> { return (await this.store.listAccounts()).map(publicAccount) }
  async getAccount(id: string): Promise<PublicAccount> { return publicAccount(await this.store.getAccount(id)) }

  async updateAccount(id: string, request: UpdateAccountRequest): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    const changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'autoConnect'>> = {}
    if (request.phoneE164 !== undefined) changes.phoneE164 = normalizeE164(request.phoneE164)
    if (request.proxyUrl !== undefined) changes.proxyUrl = validateProxy(request.proxyUrl)
    if (request.autoConnect !== undefined) changes.autoConnect = request.autoConnect
    if (this.engine.isOnline(id) && (changes.phoneE164 !== undefined || changes.proxyUrl !== undefined)) {
      throw new GatewayError('conflict', 'disconnect the account before changing its phone or proxy')
    }
    if (current.state === 'pairing' && (changes.phoneE164 !== undefined || changes.proxyUrl !== undefined)) {
      throw new GatewayError('conflict', 'cancel pairing before changing its phone or proxy')
    }
    return publicAccount(await this.store.updateAccount(id, changes))
  }

  async requestPairingCode(id: string, phoneOverride?: string): Promise<PairResult> {
    let current = await this.store.getAccount(id)
    let storedCreds = await this.store.getCreds(id)
    const activeCode = pairingCodeFromCreds(storedCreds)
    if (
      current.state === 'pairing'
      && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
      && current.pairingExpiresAt
      && current.pairingExpiresAt.getTime() > Date.now()
      && activeCode
    ) {
      this.schedulePairingExpiry(id, current.pairingExpiresAt)
      return { accountId: id, code: activeCode, expiresAt: current.pairingExpiresAt }
    }
    if (current.state === 'pairing' && current.pairingExpiresAt && current.pairingExpiresAt.getTime() <= Date.now()) {
      await this.expirePairing(id)
      current = await this.store.getAccount(id)
      storedCreds = await this.store.getCreds(id)
    }
    const isLegacyInterruptedPairing = current.state === 'linked_offline'
      && !current.deviceJid
      && current.sessionStatus === 'none'
      && storedCreds !== null
    if (isLegacyInterruptedPairing) {
      // Older releases persisted the temporary creds created while requesting
      // a code, then mislabeled a dropped pairing socket as linked_offline.
      // They contain no linked device and are safe to discard before retrying.
      await this.engine.disconnect(id)
      await this.store.clearAuth(id)
      current = await this.transitionAccount(id, 'unpaired', {
        deviceJid: '',
        autoConnect: false,
        sessionStatus: 'none',
        sessionCompleteness: 'none',
        pairingStatus: 'idle',
        pairingExpiresAt: null,
      }, 'legacy_pairing_recovered')
    } else if (current.deviceJid || storedCreds) {
      throw new GatewayError('conflict', 'account already has a session; logout before pairing again')
    }
    if (phoneOverride) current = await this.store.updateAccount(id, { phoneE164: normalizeE164(phoneOverride) })
    if (this.engine.name !== 'mock' && !current.proxyUrl) throw new GatewayError('conflict', 'a fixed proxy is required before pairing')
    const provisionalExpiry = new Date(Date.now() + 3 * 60_000)
    await this.transitionAccount(id, 'pairing', {
      pairingStatus: 'waiting_phone',
      pairingExpiresAt: provisionalExpiry,
    }, 'pairing_started')
    try {
      const result = await this.engine.pair({ accountId: id, phoneE164: current.phoneE164, proxyUrl: current.proxyUrl })
      const expiresAt = result.expiresAt.getTime() > Date.now() ? result.expiresAt : provisionalExpiry
      await this.store.updateAccount(id, { pairingStatus: 'waiting_phone', pairingExpiresAt: expiresAt })
      this.schedulePairingExpiry(id, expiresAt)
      result.expiresAt = expiresAt
      return result
    } catch (error) {
      this.clearPairingExpiry(id)
      await this.engine.disconnect(id)
      await this.store.clearAuth(id)
      await this.transitionAccount(id, 'unpaired', { pairingStatus: 'failed', pairingExpiresAt: null }, 'pairing_failed')
      this.logger.warn({ accountId: id, error: safeError(error) }, 'pairing_code_failed')
      throw new GatewayError('protocol_error', 'unable to request a pairing code; verify the phone number, proxy and network')
    }
  }

  async cancelPairing(id: string): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    if (current.state !== 'pairing' || !['waiting_phone', 'reconnecting'].includes(current.pairingStatus)) {
      return publicAccount(current)
    }
    this.clearPairingExpiry(id)
    await this.engine.disconnect(id)
    await this.store.clearAuth(id)
    return publicAccount(await this.transitionAccount(id, 'unpaired', {
      deviceJid: '',
      autoConnect: false,
      sessionStatus: 'none',
      sessionCompleteness: 'none',
      pairingStatus: 'cancelled',
      pairingExpiresAt: null,
    }, 'pairing_cancelled'))
  }

  async connect(id: string): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    if (current.state === 'restricted') throw new GatewayError('conflict', 'restricted account cannot connect; logout or replace the session first')
    if (current.state === 'reauth_required') throw new GatewayError('conflict', 'account requires a new session before connecting')
    if (current.state === 'pairing') throw new GatewayError('conflict', 'finish pairing before connecting the account')
    if (!current.deviceJid && !(await this.store.getCreds(id))) throw new GatewayError('conflict', 'account must be paired or imported before connecting')
    if (this.engine.name !== 'mock' && !current.proxyUrl) throw new GatewayError('conflict', 'a fixed proxy is required before connecting')
    await this.transitionAccount(id, 'warming', { autoConnect: true }, 'connect_requested')
    try {
      await this.engine.connect({ accountId: id, phoneE164: current.phoneE164, proxyUrl: current.proxyUrl })
      const updated = await this.transitionAccount(id, 'online_idle', { autoConnect: true, sessionStatus: 'verified' }, 'connected')
      return publicAccount(updated)
    } catch (error) {
      // A close event is emitted before Baileys rejects the in-flight connect.
      // Wait for its durable state transition so this generic failure path does
      // not overwrite terminal states such as restricted or logged out.
      await this.pendingEngineEvents.get(id)
      const failed = await this.store.getAccount(id)
      if (!['restricted', 'reauth_required', 'unpaired'].includes(failed.state)) {
        await this.transitionAccount(id, 'linked_offline', { autoConnect: false }, 'connect_failed')
      }
      this.logger.warn({ accountId: id, error: safeError(error) }, 'account_connect_failed')
      throw new GatewayError('protocol_error', 'unable to connect the saved WhatsApp session')
    }
  }

  async disconnect(id: string): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    if (current.state === 'pairing' && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)) {
      return this.cancelPairing(id)
    }
    await this.engine.disconnect(id)
    const state: AccountState = ['restricted', 'reauth_required', 'unpaired'].includes(current.state)
      ? current.state
      : current.deviceJid || await this.store.getCreds(id) ? 'linked_offline' : 'unpaired'
    return publicAccount(await this.transitionAccount(id, state, { autoConnect: false }, 'manual_disconnect'))
  }

  async logout(id: string): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    if (!(await this.store.getCreds(id)) && !current.deviceJid) return publicAccount(current)
    try { await this.engine.logout({ accountId: id, phoneE164: current.phoneE164, proxyUrl: current.proxyUrl }) } catch (error) {
      this.logger.warn({ accountId: id, error: safeError(error) }, 'account_logout_failed')
      throw new GatewayError('protocol_error', 'WhatsApp did not confirm logout')
    }
    await this.pendingEngineEvents.get(id)
    await this.store.clearAuth(id)
    this.clearPairingExpiry(id)
    return publicAccount(await this.transitionAccount(id, 'unpaired', { deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'idle', pairingExpiresAt: null }, 'manual_logout'))
  }

  async importSession(id: string, session: unknown, proxyUrl?: string): Promise<{ account: PublicAccount; format: string; status: string }> {
    const parsed = parseImportedSession(session)
    let current: Account | null = null
    try {
      current = await this.store.getAccount(id)
    } catch (error) {
      if (!(error instanceof GatewayError) || error.code !== 'not_found') throw error
    }
    if (current === null) {
      if (!/^[A-Za-z0-9_.-]{1,80}$/.test(id)) throw new GatewayError('invalid_argument', 'account id contains unsupported characters')
      if (proxyUrl === undefined || !proxyUrl.trim()) throw new GatewayError('invalid_argument', 'proxyUrl is required when importing a new account')
      const created = await this.store.createImportedAccount({
        id,
        phoneE164: phoneFromDeviceJid(parsed.deviceJid),
        proxyUrl: validateProxy(proxyUrl),
        state: 'linked_offline',
        deviceJid: parsed.deviceJid,
        autoConnect: false,
        sessionStatus: 'pending_verification',
        sessionCompleteness: parsed.completeness,
      }, parsed.auth)
      return { account: publicAccount(created), format: parsed.completeness === 'full' ? 'parloq-baileys-session/v1' : 'baileys-creds', status: 'pending_verification' }
    }
    if (this.engine.isOnline(id) || current.state === 'pairing') throw new GatewayError('conflict', 'disconnect the account before importing a session')
    const nextProxy = proxyUrl === undefined ? current.proxyUrl : validateProxy(proxyUrl)
    if (!nextProxy) throw new GatewayError('invalid_argument', 'a fixed proxy is required before importing a session')
    await this.store.replaceAuth(id, parsed.auth)
    const changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness'>> = {
      deviceJid: parsed.deviceJid,
      autoConnect: false,
      sessionStatus: 'pending_verification',
      sessionCompleteness: parsed.completeness,
    }
    if (proxyUrl !== undefined) await this.store.updateAccount(id, { proxyUrl: nextProxy })
    const account = await this.transitionAccount(id, 'linked_offline', { ...changes, pairingStatus: 'idle', pairingExpiresAt: null }, 'session_imported')
    return { account: publicAccount(account), format: parsed.completeness === 'full' ? 'parloq-baileys-session/v1' : 'baileys-creds', status: 'pending_verification' }
  }

  async exportSession(id: string): Promise<{ session: unknown; format: string; status: string }> {
    await this.store.getAccount(id)
    if (this.engine.isOnline(id)) throw new GatewayError('conflict', 'disconnect the account before exporting its session')
    const creds = await this.store.getCreds(id)
    if (!creds) throw new GatewayError('conflict', 'account has no Baileys session to export')
    const keys = await this.store.getAllKeys(id)
    return { session: exportSession({ creds, keys }), format: 'parloq-baileys-session/v1', status: 'ready' }
  }

  async sendText(id: string, request: SendTextRequest): Promise<Message> {
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(request.messageId)) throw new GatewayError('invalid_argument', 'messageId is required and contains unsupported characters')
    const recipientE164 = normalizeE164(request.toE164)
    if (!request.text.trim() || [...request.text].length > 4_096) throw new GatewayError('invalid_argument', 'text is required and must be at most 4096 characters')
    const current = await this.store.getAccount(id)
    if (!['online_idle', 'sending'].includes(current.state) || !this.engine.isOnline(id)) throw new GatewayError('account_offline', 'account is not connected')
    const now = new Date()
    const result = await this.store.createMessage({ messageId: request.messageId, accountId: id, recipientE164, providerMessageId: '', status: 'queued', errorCode: '', queuedAt: now, sentAt: null, deliveredAt: null, updatedAt: now })
    if (!result.created) {
      if (result.message.accountId !== id || result.message.recipientE164 !== recipientE164) throw new GatewayError('conflict', 'messageId was already used for a different request')
      return result.message
    }
    const depth = this.queueDepth.get(id) ?? 0
    if (depth >= this.maxQueueSize) {
      const failed = await this.store.updateMessage(request.messageId, { status: 'failed', errorCode: 'queue_full' })
      this.webhook.deliver(failed)
      throw new GatewayError('queue_full', 'account send queue is full')
    }
    this.queueDepth.set(id, depth + 1)
    const previous = this.queueTail.get(id) ?? Promise.resolve()
    const next = previous.catch(() => undefined).then(() => this.processSend(request.messageId, id, recipientE164, request.text))
    this.queueTail.set(id, next)
    void next.finally(() => {
      this.queueDepth.set(id, Math.max(0, (this.queueDepth.get(id) ?? 1) - 1))
      if (this.queueTail.get(id) === next) this.queueTail.delete(id)
    })
    this.webhook.deliver(result.message)
    return result.message
  }

  async getMessage(id: string): Promise<Message> { return this.store.getMessage(id) }

  private async transitionAccount(
    id: string,
    state: AccountState,
    changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus'>>,
    reasonCategory: string,
    providerCode?: string,
  ): Promise<Account> {
    const result = await this.store.transitionAccount(id, state, changes, reasonCategory, providerCode)
    if (result.changed) {
      const occurredAt = result.account.stateChangedAt
      this.webhook.deliverAccountState({
        event: 'account.state',
        eventId: newPublicId('ast'),
        accountId: id,
        fromState: result.fromState,
        toState: state,
        reasonCategory,
        ...(providerCode ? { providerCode } : {}),
        occurredAt,
      })
    }
    return result.account
  }

  private clearPairingExpiry(id: string): void {
    const timer = this.pairingExpiryTimers.get(id)
    if (timer) clearTimeout(timer)
    this.pairingExpiryTimers.delete(id)
  }

  private schedulePairingExpiry(id: string, expiresAt: Date): void {
    this.clearPairingExpiry(id)
    const delay = Math.max(0, expiresAt.getTime() - Date.now())
    const timer = setTimeout(() => {
      this.pairingExpiryTimers.delete(id)
      void this.expirePairing(id).catch((error: unknown) => {
        this.logger.warn({ accountId: id, error: safeError(error) }, 'pairing_expiry_failed')
      })
    }, delay)
    timer.unref()
    this.pairingExpiryTimers.set(id, timer)
  }

  private async expirePairing(id: string): Promise<Account> {
    const current = await this.store.getAccount(id)
    if (
      current.state !== 'pairing'
      || !['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
      || current.sessionStatus === 'verified'
    ) {
      this.clearPairingExpiry(id)
      return current
    }
    if (current.pairingExpiresAt && current.pairingExpiresAt.getTime() > Date.now()) {
      this.schedulePairingExpiry(id, current.pairingExpiresAt)
      return current
    }
    this.clearPairingExpiry(id)
    await this.engine.disconnect(id)
    await this.store.clearAuth(id)
    return this.transitionAccount(id, 'unpaired', {
      deviceJid: '',
      autoConnect: false,
      sessionStatus: 'none',
      sessionCompleteness: 'none',
      pairingStatus: 'expired',
    }, 'pairing_expired')
  }

  private async processSend(messageId: string, accountId: string, recipient: string, text: string): Promise<void> {
    try {
      const intervalMs = Math.ceil(1_000 / this.sendQps)
      const now = Date.now()
      const allowedAt = Math.max(now, this.nextSendAt.get(accountId) ?? now)
      this.nextSendAt.set(accountId, allowedAt + intervalMs)
      if (allowedAt > now) {
        await new Promise((resolve) => setTimeout(resolve, allowedAt - now))
      }
      const providerMessageId = await this.engine.send(accountId, recipient, text)
      const sent = await this.store.updateMessage(messageId, { providerMessageId, status: 'sent', errorCode: '', sentAt: new Date() })
      this.webhook.deliver(sent)
    } catch (error) {
      const failed = await this.store.updateMessage(messageId, { status: 'failed', errorCode: 'send_failed' })
      this.webhook.deliver(failed)
      this.logger.warn({ messageId, accountId, error: safeError(error) }, 'message_send_failed')
    }
  }

  private async handleEngineEvent(event: EngineEvent): Promise<void> {
    try {
      if (event.kind === 'connected') {
        const current = await this.store.getAccount(event.accountId)
        const completedPairing = current.state === 'pairing' && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
        if (completedPairing) this.clearPairingExpiry(event.accountId)
        await this.transitionAccount(event.accountId, 'online_idle', {
          deviceJid: event.deviceJid || current.deviceJid,
          autoConnect: true,
          sessionStatus: 'verified',
          ...(completedPairing ? { pairingStatus: 'verified' as const, pairingExpiresAt: null } : {}),
          metadataSyncStatus: 'syncing',
        }, 'connected')
        try {
          const quality = await this.engine.getQuality(event.accountId)
          await this.store.updateAccount(event.accountId, {
            metadataSyncStatus: quality.hasAvatar !== null || quality.groupCount !== null ? 'ready' : 'unsupported',
            ...quality,
          })
        } catch {
          await this.store.updateAccount(event.accountId, { metadataSyncStatus: 'failed' })
        }
      } else if (event.kind === 'pairing_restarting') {
        const current = await this.store.getAccount(event.accountId)
        if (
          current.state === 'pairing'
          && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
          && current.pairingExpiresAt !== null
          && current.pairingExpiresAt.getTime() > Date.now()
        ) {
          await this.store.updateAccount(event.accountId, { pairingStatus: 'reconnecting' })
        }
      } else if (event.kind === 'disconnected') {
        const current = await this.store.getAccount(event.accountId)
        const pairingActive = current.state === 'pairing'
          && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
          && current.pairingExpiresAt !== null
          && current.pairingExpiresAt.getTime() > Date.now()
        if (pairingActive) {
          this.clearPairingExpiry(event.accountId)
          await this.store.clearAuth(event.accountId)
          await this.transitionAccount(event.accountId, 'unpaired', {
            deviceJid: '',
            autoConnect: false,
            sessionStatus: 'none',
            sessionCompleteness: 'none',
            pairingStatus: 'failed',
            pairingExpiresAt: null,
          }, 'pairing_connection_lost', event.providerCode)
          return
        }
        if (current.state === 'pairing' && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)) {
          await this.expirePairing(event.accountId)
          return
        }
        const hasLinkedSession = current.sessionStatus === 'verified' || Boolean(current.deviceJid)
        if (hasLinkedSession) {
          await this.transitionAccount(event.accountId, 'linked_offline', {}, event.reasonCategory, event.providerCode)
        } else {
          // A pairing socket can close after a code was issued but before the
          // phone authorizes the companion. Such a socket cannot complete the
          // handshake and must never be presented as a linked account.
          await this.store.clearAuth(event.accountId)
          await this.transitionAccount(
            event.accountId,
            'unpaired',
            { deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'failed', pairingExpiresAt: null },
            'pairing_connection_lost',
            event.providerCode,
          )
        }
      } else if (event.kind === 'logged_out') {
        this.clearPairingExpiry(event.accountId)
        await this.store.clearAuth(event.accountId)
        await this.transitionAccount(event.accountId, 'unpaired', { deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'failed', pairingExpiresAt: null }, event.reasonCategory, event.providerCode)
      } else if (event.kind === 'reauth_required') {
        this.clearPairingExpiry(event.accountId)
        await this.transitionAccount(event.accountId, 'reauth_required', { autoConnect: false }, event.reasonCategory, event.providerCode)
      } else if (event.kind === 'restricted') {
        this.clearPairingExpiry(event.accountId)
        await this.transitionAccount(event.accountId, 'restricted', { autoConnect: false }, event.reasonCategory, event.providerCode)
      } else if (event.kind === 'delivered') {
        const message = await this.store.markDeliveredByProvider(event.accountId, event.providerMessageId)
        if (message) this.webhook.deliver(message)
      }
    } catch (error) {
      this.logger.warn({ accountId: event.accountId, kind: event.kind, error: safeError(error) }, 'engine_event_persist_failed')
    }
  }
}
