import { randomInt } from 'node:crypto'
import type { Logger } from 'pino'
import type { Account, AccountResourceSnapshot, AccountState, Message, PublicAccount } from './domain.js'
import { GatewayError, defaultSyncPolicy, normalizeE164, normalizeMessageTarget, normalizeSyncPolicy, publicAccount, safeError, validateProxy, type AccountAvatar, type MetadataSyncResponse, type SyncPolicy } from './domain.js'
import { PAIRING_CODE_TTL_MS, type EngineEvent, type PairResult, type ProtocolEngine } from './engine.js'
import { BAILEYS_VERSION, exportSession, parseImportedSession, phoneFromDeviceJid } from './session.js'
import type { Store } from './store.js'
import { newPublicId } from './snowflake.js'
import { WebhookClient } from './webhook.js'
import { normalizeOutboundMessage, type OutboundMessage, type SendMessageRequest } from './message-content.js'
import { engineAccount } from './versioned-engine.js'
import { diagnosePairingFailure } from './failure-diagnosis.js'
import type { FailureDiagnosis } from './domain.js'

export interface CreateAccountRequest { id?: string; protocolDefinitionId?: string; protocolVersion?: string; phoneE164: string; proxyUrl?: string; connectionPolicy?: 'on_demand' | 'always_on'; idleDisconnectSeconds?: number; postVerifyGraceSeconds?: number; syncPolicy?: SyncPolicy }
export interface UpdateAccountRequest { phoneE164?: string; proxyUrl?: string; protocolDefinitionId?: string; protocolVersion?: string; autoConnect?: boolean; connectionPolicy?: 'on_demand' | 'always_on'; idleDisconnectSeconds?: number; postVerifyGraceSeconds?: number; syncPolicy?: SyncPolicy }
export interface MetadataSyncRequest { syncPolicy?: SyncPolicy }
export interface DeleteAccountResult { accountId: string; deleted: boolean; providerLogoutConfirmed: boolean }
export type PairingCodeMode = 'fixed' | 'random_numeric' | 'random_alphanumeric'

export function customPairingCode(
  mode: PairingCodeMode | undefined,
  fixedPairingCode: string | undefined,
): string | undefined {
  if (mode === undefined || mode === 'random_alphanumeric') return undefined
  if (mode === 'random_numeric') {
    return String(randomInt(0, 100_000_000)).padStart(8, '0')
  }
  if (mode !== 'fixed') {
    throw new GatewayError('invalid_argument', 'pairingCodeMode is invalid')
  }
  const normalized = fixedPairingCode?.trim().toUpperCase() || ''
  if (!/^[A-Z0-9]{8}$/.test(normalized)) {
    throw new GatewayError('invalid_argument', 'fixedPairingCode must contain exactly 8 letters or digits')
  }
  return normalized
}

function metadataResourcesComplete(
  policy: SyncPolicy,
  resources: AccountResourceSnapshot,
): boolean {
  return (!policy.contacts || resources.contactsStatus === 'complete')
    && (!policy.groupDetails || resources.groupsStatus === 'complete')
}

function pairingCodeFromCreds(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const code = (value as { pairingCode?: unknown }).pairingCode
  return typeof code === 'string' && /^[A-Z0-9]{8}$/i.test(code) ? code : null
}

export class GatewayService {
  private readonly queueDepth = new Map<string, number>()
  private readonly queueTail = new Map<string, Promise<void>>()
  private readonly activeMessageIds = new Set<string>()
  private readonly nextSendAt = new Map<string, number>()
  private readonly pendingEngineEvents = new Map<string, Promise<void>>()
  private readonly pairingExpiryTimers = new Map<string, ReturnType<typeof setTimeout>>()
  private readonly idleDisconnectTimers = new Map<string, ReturnType<typeof setTimeout>>()

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

  async protocolInfo() {
    const runtime = this.engine.protocolVersionInfo
      ? await this.engine.protocolVersionInfo()
      : {
          currentWaWebVersion: null,
          latestWaWebVersion: null,
          versionStatus: 'unavailable' as const,
          checkedAt: null,
          checkError: null,
        }
    return {
      protocol: 'baileys',
      name: 'Baileys Web',
      baileysVersion: BAILEYS_VERSION,
      engine: this.engine.name,
      ...runtime,
    }
  }

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
      await this.clearRequestedHistory(account.id)
      await this.transitionAccount(account.id, 'unpaired', {
        deviceJid: '',
        autoConnect: false,
        sessionStatus: 'none',
        sessionCompleteness: 'none',
        pairingStatus: 'failed',
        pairingExpiresAt: null,
      }, 'pairing_interrupted')
    }
    for (const account of accounts.filter((item) => item.connectionPolicy === 'on_demand' && ['online_idle', 'sending'].includes(item.state))) {
      await this.transitionAccount(account.id, 'linked_offline', { autoConnect: false }, 'gateway_restart')
    }
    for (const account of accounts.filter((item) => item.connectionPolicy === 'always_on' && item.autoConnect && item.deviceJid)) {
      void this.connect(account.id).catch((error: unknown) => this.logger.warn({ accountId: account.id, error: safeError(error) }, 'account_restore_failed'))
    }
  }

  async close(): Promise<void> {
    for (const timer of this.pairingExpiryTimers.values()) clearTimeout(timer)
    this.pairingExpiryTimers.clear()
    for (const timer of this.idleDisconnectTimers.values()) clearTimeout(timer)
    this.idleDisconnectTimers.clear()
    await this.engine.close()
    await this.store.close()
  }
  async ready(): Promise<void> { await this.store.ready(); await this.engine.ready() }

  async createAccount(request: CreateAccountRequest): Promise<PublicAccount> {
    const phoneE164 = normalizeE164(request.phoneE164)
    const proxyUrl = validateProxy(request.proxyUrl ?? '')
    const connectionPolicy = request.connectionPolicy === 'always_on' ? 'always_on' : 'on_demand'
    const idleDisconnectSeconds = Math.min(86_400, Math.max(60, request.idleDisconnectSeconds ?? 600))
    const postVerifyGraceSeconds = Math.min(3_600, Math.max(0, request.postVerifyGraceSeconds ?? 120))
    const syncPolicy = normalizeSyncPolicy(request.syncPolicy ?? defaultSyncPolicy)
    const protocolDefinitionId = request.protocolDefinitionId?.trim() || '0'
    const protocolVersion = request.protocolVersion?.trim() || BAILEYS_VERSION
    if (!/^\d{1,20}$/.test(protocolDefinitionId)) throw new GatewayError('invalid_argument', 'protocolDefinitionId must be a Snowflake identifier')
    if (!/^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$/.test(protocolVersion)) throw new GatewayError('invalid_argument', 'protocolVersion has an invalid format')
    const id = request.id?.trim() || newPublicId('wa')
    if (!/^[A-Za-z0-9_.-]{1,80}$/.test(id)) throw new GatewayError('invalid_argument', 'account id contains unsupported characters')
    try {
      return publicAccount(await this.store.createAccount({ id, protocolDefinitionId, protocolVersion, phoneE164, proxyUrl, state: 'unpaired', connectionPolicy, idleDisconnectSeconds, postVerifyGraceSeconds, syncPolicy }))
    } catch (error) {
      if (!(error instanceof GatewayError) || error.code !== 'conflict') throw error
      // A control-plane transaction may fail after the gateway account was
      // created. Reclaim only a credential-free, unused row for the exact
      // phone so a later landing-page retry is not permanently blocked.
      const reclaimed = await this.store.claimUnpairedAccount({ id, protocolDefinitionId, protocolVersion, phoneE164, proxyUrl, connectionPolicy, idleDisconnectSeconds, postVerifyGraceSeconds, syncPolicy })
      if (!reclaimed) throw error
      return publicAccount(reclaimed)
    }
  }

  async listAccounts(): Promise<PublicAccount[]> { return (await this.store.listAccounts()).map(publicAccount) }
  async getAccount(id: string): Promise<PublicAccount> { return publicAccount(await this.store.getAccount(id)) }

  async updateAccount(id: string, request: UpdateAccountRequest): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    const changes: Partial<Pick<Account, 'phoneE164' | 'proxyUrl' | 'autoConnect' | 'connectionPolicy' | 'idleDisconnectSeconds' | 'postVerifyGraceSeconds' | 'syncPolicy'>> = {}
    if (request.protocolDefinitionId !== undefined) {
      const protocolDefinitionId = request.protocolDefinitionId.trim()
      if (!/^\d{1,20}$/.test(protocolDefinitionId)) throw new GatewayError('invalid_argument', 'protocolDefinitionId must be a Snowflake identifier')
      if (protocolDefinitionId !== current.protocolDefinitionId) throw new GatewayError('conflict', 'an existing account cannot change its protocol binding')
    }
    if (request.protocolVersion !== undefined) {
      const protocolVersion = request.protocolVersion.trim()
      if (!/^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$/.test(protocolVersion)) throw new GatewayError('invalid_argument', 'protocolVersion has an invalid format')
      if (protocolVersion !== current.protocolVersion) throw new GatewayError('conflict', 'an existing account cannot change its protocol binding')
    }
    if (request.phoneE164 !== undefined) {
      const phoneE164 = normalizeE164(request.phoneE164)
      if (phoneE164 !== current.phoneE164) changes.phoneE164 = phoneE164
    }
    if (request.proxyUrl !== undefined) {
      const proxyUrl = validateProxy(request.proxyUrl)
      if (proxyUrl !== current.proxyUrl) changes.proxyUrl = proxyUrl
    }
    if (request.autoConnect !== undefined && request.autoConnect !== current.autoConnect) changes.autoConnect = request.autoConnect
    if (request.connectionPolicy !== undefined && request.connectionPolicy !== current.connectionPolicy) changes.connectionPolicy = request.connectionPolicy
    if (request.idleDisconnectSeconds !== undefined) {
      const idleDisconnectSeconds = Math.min(86_400, Math.max(60, request.idleDisconnectSeconds))
      if (idleDisconnectSeconds !== current.idleDisconnectSeconds) changes.idleDisconnectSeconds = idleDisconnectSeconds
    }
    if (request.postVerifyGraceSeconds !== undefined) {
      const postVerifyGraceSeconds = Math.min(3_600, Math.max(0, request.postVerifyGraceSeconds))
      if (postVerifyGraceSeconds !== current.postVerifyGraceSeconds) changes.postVerifyGraceSeconds = postVerifyGraceSeconds
    }
    if (request.syncPolicy !== undefined) {
      const syncPolicy = normalizeSyncPolicy(request.syncPolicy)
      if ((Object.keys(syncPolicy) as Array<keyof SyncPolicy>).some((key) => syncPolicy[key] !== current.syncPolicy[key])) changes.syncPolicy = syncPolicy
    }
    if (this.engine.isOnline(id) && (changes.phoneE164 !== undefined || changes.proxyUrl !== undefined)) {
      throw new GatewayError('conflict', 'disconnect the account before changing its phone or proxy')
    }
    if (current.state === 'pairing' && (changes.phoneE164 !== undefined || changes.proxyUrl !== undefined)) {
      throw new GatewayError('conflict', 'cancel pairing before changing its phone or proxy')
    }
    return publicAccount(await this.store.updateAccount(id, changes))
  }

  async requestPairingCode(
    id: string,
    phoneOverride?: string,
    pairingCodeMode?: PairingCodeMode,
    fixedPairingCode?: string,
  ): Promise<PairResult> {
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
    if (current.syncPolicy.contacts || current.syncPolicy.groupDetails) {
      // Prepare the natural post-pairing socket for the one-shot history
      // import. The later metadata task can then reuse that connection rather
      // than interrupting the phone's companion-device initialization.
      current = await this.store.updateAccount(id, {
        metadata: { ...current.metadata, requestContactsHistory: true },
      })
    }
    const requestedPairingCode = customPairingCode(pairingCodeMode, fixedPairingCode)
    const provisionalExpiry = new Date(Date.now() + PAIRING_CODE_TTL_MS)
    await this.transitionAccount(id, 'pairing', {
      pairingStatus: 'waiting_phone',
      pairingExpiresAt: provisionalExpiry,
    }, 'pairing_started')
    try {
      const result = await this.engine.pair({
        ...engineAccount(current),
        ...(requestedPairingCode
          ? { customPairingCode: requestedPairingCode }
          : {}),
      })
      const engineExpiry = result.expiresAt.getTime() > Date.now() ? result.expiresAt : provisionalExpiry
      const expiresAt = new Date(Math.min(engineExpiry.getTime(), provisionalExpiry.getTime()))
      await this.store.updateAccount(id, { pairingStatus: 'waiting_phone', pairingExpiresAt: expiresAt })
      this.schedulePairingExpiry(id, expiresAt)
      result.expiresAt = expiresAt
      return result
    } catch (error) {
      const failure = diagnosePairingFailure(error, { stage: 'pairing_start' })
      this.clearPairingExpiry(id)
      await this.engine.disconnect(id)
      await this.store.clearAuth(id)
      await this.clearRequestedHistory(id)
      await this.transitionAccount(
        id,
        'unpaired',
        { pairingStatus: 'failed', pairingExpiresAt: null },
        'pairing_failed',
        failure.protocolCode,
        failure,
      )
      this.logger.warn({ accountId: id, error: safeError(error) }, 'pairing_code_failed')
      throw new GatewayError(
        'protocol_error',
        'unable to request a pairing code; verify the phone number, proxy and network',
        failure,
      )
    }
  }

  async requestReauthenticationCode(
    id: string,
    phoneOverride?: string,
    pairingCodeMode?: PairingCodeMode,
    fixedPairingCode?: string,
  ): Promise<PairResult> {
    const current = await this.store.getAccount(id)
    if (current.state !== 'reauth_required') {
      throw new GatewayError('conflict', 'account does not require reauthentication')
    }
    this.clearIdleDisconnect(id)
    this.clearPairingExpiry(id)
    await this.engine.disconnect(id)
    await this.store.clearAuth(id)
    await this.transitionAccount(id, 'unpaired', {
      deviceJid: '',
      autoConnect: false,
      sessionStatus: 'none',
      sessionCompleteness: 'none',
      pairingStatus: 'idle',
      pairingExpiresAt: null,
      metadataSyncStatus: 'pending',
    }, 'reauthentication_started')
    return this.requestPairingCode(
      id,
      phoneOverride,
      pairingCodeMode,
      fixedPairingCode,
    )
  }

  async cancelPairing(id: string): Promise<PublicAccount> {
    const current = await this.store.getAccount(id)
    if (current.state !== 'pairing' || !['waiting_phone', 'reconnecting'].includes(current.pairingStatus)) {
      return publicAccount(current)
    }
    this.clearPairingExpiry(id)
    await this.engine.disconnect(id)
    await this.store.clearAuth(id)
    await this.clearRequestedHistory(id)
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
    if (this.engine.isOnline(id) && ['online_idle', 'sending'].includes(current.state)) return publicAccount(current)
    if (current.state === 'restricted') throw new GatewayError('conflict', 'restricted account cannot connect; logout or replace the session first')
    if (current.state === 'reauth_required') throw new GatewayError('conflict', 'account requires a new session before connecting')
    if (current.state === 'pairing') throw new GatewayError('conflict', 'finish pairing before connecting the account')
    if (!current.deviceJid && !(await this.store.getCreds(id))) throw new GatewayError('conflict', 'account must be paired or imported before connecting')
    if (this.engine.name !== 'mock' && !current.proxyUrl) throw new GatewayError('conflict', 'a fixed proxy is required before connecting')
    this.clearIdleDisconnect(id)
    const autoConnect = current.connectionPolicy === 'always_on'
    await this.transitionAccount(id, 'warming', { autoConnect }, 'connect_requested')
    try {
      await this.engine.connect(engineAccount(current))
      const updated = await this.transitionAccount(id, 'online_idle', { autoConnect, sessionStatus: 'verified' }, 'connected')
      this.scheduleIdleDisconnect(updated)
      return publicAccount(updated)
    } catch (error) {
      // A close event is emitted before Baileys rejects the in-flight connect.
      // Wait for its durable state transition so this generic failure path does
      // not overwrite terminal states such as restricted or logged out.
      await this.pendingEngineEvents.get(id)
      if (current.connectionPolicy !== 'always_on') {
        // An explicit on-demand connect owns its retry lifecycle. Stop the
        // engine's background retry after the request has conclusively failed.
        await this.engine.disconnect(id)
      }
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
    this.clearIdleDisconnect(id)
    await this.engine.disconnect(id)
    const state: AccountState = ['restricted', 'reauth_required', 'unpaired'].includes(current.state)
      ? current.state
      : current.deviceJid || await this.store.getCreds(id) ? 'linked_offline' : 'unpaired'
    return publicAccount(await this.transitionAccount(id, state, { autoConnect: false }, 'manual_disconnect'))
  }

  async deleteAccount(id: string): Promise<DeleteAccountResult> {
    let current: Account
    try {
      current = await this.store.getAccount(id)
    } catch (error) {
      if (error instanceof GatewayError && error.code === 'not_found') {
        return { accountId: id, deleted: false, providerLogoutConfirmed: false }
      }
      throw error
    }
    if ((this.queueDepth.get(id) ?? 0) > 0) {
      throw new GatewayError('conflict', 'account still has messages in flight')
    }

    this.clearPairingExpiry(id)
    this.clearIdleDisconnect(id)
    let providerLogoutConfirmed = false
    const hasSession = Boolean(current.deviceJid || await this.store.getCreds(id))
    if (hasSession) {
      try {
        await this.engine.logout(engineAccount(current))
        providerLogoutConfirmed = true
      } catch (error) {
        this.logger.warn({ accountId: id, error: safeError(error) }, 'account_delete_provider_logout_failed')
        try { await this.engine.disconnect(id) } catch { /* local purge remains authoritative */ }
      }
    } else {
      try { await this.engine.disconnect(id) } catch { /* no persisted session to preserve */ }
    }

    await this.pendingEngineEvents.get(id)
    const deleted = await this.store.deleteAccount(id)
    this.queueDepth.delete(id)
    this.queueTail.delete(id)
    this.nextSendAt.delete(id)
    this.pendingEngineEvents.delete(id)
    return { accountId: id, deleted, providerLogoutConfirmed }
  }

  async importSession(
    id: string,
    session: unknown,
    proxyUrl?: string,
    protocolDefinitionId = '0',
    protocolVersion = BAILEYS_VERSION,
  ): Promise<{ account: PublicAccount; format: string; status: string }> {
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
        protocolDefinitionId,
        protocolVersion,
        phoneE164: phoneFromDeviceJid(parsed.deviceJid),
        proxyUrl: validateProxy(proxyUrl),
        state: 'linked_offline',
        deviceJid: parsed.deviceJid,
        autoConnect: false,
        sessionStatus: 'pending_verification',
        sessionCompleteness: parsed.completeness,
        connectionPolicy: 'on_demand',
        idleDisconnectSeconds: 600,
        postVerifyGraceSeconds: 120,
        syncPolicy: { ...defaultSyncPolicy },
      }, parsed.auth)
      return { account: publicAccount(created), format: parsed.completeness === 'full' ? 'parloq-baileys-session/v1' : 'baileys-creds', status: 'pending_verification' }
    }
    if (
      current.protocolDefinitionId !== protocolDefinitionId
      || current.protocolVersion !== protocolVersion
    ) {
      throw new GatewayError('conflict', 'an existing account cannot change its protocol binding')
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
    const current = await this.store.getAccount(id)
    if (this.engine.isOnline(id)) throw new GatewayError('conflict', 'disconnect the account before exporting its session')
    const creds = await this.store.getCreds(id)
    if (!creds) throw new GatewayError('conflict', 'account has no Baileys session to export')
    const keys = await this.store.getAllKeys(id)
    return { session: exportSession({ creds, keys }, current.protocolVersion), format: 'parloq-baileys-session/v1', status: 'ready' }
  }

  async syncAccountMetadata(id: string, request: MetadataSyncRequest = {}): Promise<MetadataSyncResponse> {
    let current = await this.store.getAccount(id)
    if (request.syncPolicy !== undefined) {
      current = await this.store.updateAccount(id, {
        syncPolicy: normalizeSyncPolicy(request.syncPolicy),
      })
    }
    if (current.state === 'restricted' || current.state === 'reauth_required' || current.state === 'pairing') {
      throw new GatewayError('conflict', 'account is not available for metadata synchronization')
    }
    if (current.state === 'sending' || (this.queueDepth.get(id) ?? 0) > 0) {
      throw new GatewayError('conflict', 'account has messages in flight; retry metadata synchronization later')
    }
    // Metadata collection owns the socket for this bounded operation. Prevent
    // the post-verify/idle timer from closing it halfway through history wait.
    this.clearIdleDisconnect(id)
    const wasOnline = this.engine.isOnline(id)
    const postVerifyDeadline = wasOnline
      && current.state === 'online_idle'
      && current.pairingStatus === 'verified'
      && current.metadataSyncStatus === 'pending'
      ? current.stateChangedAt.getTime() + current.postVerifyGraceSeconds * 1_000
      : null
    const requestContactsHistory = current.syncPolicy.contacts || current.syncPolicy.groupDetails
    const historyAlreadyPrepared = current.metadata.requestContactsHistory === true
    let avatar: AccountAvatar | null | undefined
    let avatarIncluded = false
    let resources: AccountResourceSnapshot | undefined
    let connectionFailed = false
    try {
      if (requestContactsHistory && !historyAlreadyPrepared) {
        current = await this.store.updateAccount(id, {
          metadata: { ...current.metadata, requestContactsHistory: true },
        })
        // Existing sessions need one controlled reconnect to opt into full
        // history. Freshly paired sessions already opened with this flag and
        // are deliberately left untouched.
        if (wasOnline) await this.engine.disconnect(id)
      }
      if (!this.engine.isOnline(id)) {
        try {
          await this.connect(id)
        } catch (error) {
          connectionFailed = true
          throw error
        }
        current = await this.store.getAccount(id)
      }
      await this.store.updateAccount(id, { metadataSyncStatus: 'syncing' })
      const synced = await this.syncMetadata(await this.store.getAccount(id))
      avatar = synced.avatar
      avatarIncluded = synced.avatarIncluded
      resources = synced.resources
    } catch (error) {
      await this.store.updateAccount(id, { metadataSyncStatus: 'failed' })
      throw error
    } finally {
      let latest = await this.store.getAccount(id)
      if (requestContactsHistory) {
        await this.clearRequestedHistory(id)
        latest = await this.store.getAccount(id)
      }
      const shouldRemainOnline = wasOnline || latest.connectionPolicy === 'always_on'
      if (shouldRemainOnline && !connectionFailed && !this.engine.isOnline(id)) {
        try { await this.connect(id) } catch (error) {
          this.logger.warn({ accountId: id, error: safeError(error) }, 'metadata_sync_online_restore_failed')
        }
      } else if (!shouldRemainOnline && this.engine.isOnline(id)) {
        await this.disconnect(id)
      }
      if (shouldRemainOnline && this.engine.isOnline(id)) {
        const remainingGraceSeconds = postVerifyDeadline === null
          ? undefined
          : Math.max(0, Math.ceil((postVerifyDeadline - Date.now()) / 1_000))
        this.scheduleIdleDisconnect(
          await this.store.getAccount(id),
          remainingGraceSeconds,
        )
      }
    }
    const response = publicAccount(await this.store.getAccount(id))
    return {
      ...response,
      ...(avatarIncluded ? { avatar: avatar ?? null } : {}),
      ...(resources ? { resources } : {}),
    }
  }

  async sendMessage(id: string, request: SendMessageRequest): Promise<Message> {
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(request.messageId)) throw new GatewayError('invalid_argument', 'messageId is required and contains unsupported characters')
    const recipientE164 = normalizeMessageTarget(request.toE164)
    const message = normalizeOutboundMessage(request)
    let current = await this.store.getAccount(id)
    if (!this.engine.isOnline(id) && current.connectionPolicy === 'on_demand' && current.state === 'linked_offline') {
      await this.connect(id)
      current = await this.store.getAccount(id)
    }
    if (!['online_idle', 'sending'].includes(current.state) || !this.engine.isOnline(id)) throw new GatewayError('account_offline', 'account is not connected')
    this.clearIdleDisconnect(id)
    const now = new Date()
    const result = await this.store.createMessage({ messageId: request.messageId, accountId: id, recipientE164, providerMessageId: '', status: 'queued', errorCode: '', queuedAt: now, sentAt: null, deliveredAt: null, updatedAt: now })
    if (!result.created) {
      if (result.message.accountId !== id || result.message.recipientE164 !== recipientE164) throw new GatewayError('conflict', 'messageId was already used for a different request')
      if (result.message.status === 'queued' && !this.activeMessageIds.has(request.messageId)) {
        this.enqueueMessage(request.messageId, id, recipientE164, message)
      }
      return result.message
    }
    try {
      this.enqueueMessage(request.messageId, id, recipientE164, message)
    } catch (error) {
      const failed = await this.store.updateMessage(request.messageId, { status: 'failed', errorCode: 'queue_full' })
      this.webhook.deliver(failed)
      throw error
    }
    this.webhook.deliver(result.message)
    return result.message
  }

  private enqueueMessage(
    messageId: string,
    accountId: string,
    recipientE164: string,
    message: OutboundMessage,
  ): void {
    if (this.activeMessageIds.has(messageId)) return
    const depth = this.queueDepth.get(accountId) ?? 0
    if (depth >= this.maxQueueSize) {
      throw new GatewayError('queue_full', 'account send queue is full')
    }
    this.activeMessageIds.add(messageId)
    this.queueDepth.set(accountId, depth + 1)
    const previous = this.queueTail.get(accountId) ?? Promise.resolve()
    const next = previous.catch(() => undefined).then(() => this.processSend(messageId, accountId, recipientE164, message))
    this.queueTail.set(accountId, next)
    void next.finally(() => {
      this.activeMessageIds.delete(messageId)
      this.queueDepth.set(accountId, Math.max(0, (this.queueDepth.get(accountId) ?? 1) - 1))
      if (this.queueTail.get(accountId) === next) this.queueTail.delete(accountId)
    })
  }

  async getMessage(id: string): Promise<Message> { return this.store.getMessage(id) }

  private async transitionAccount(
    id: string,
    state: AccountState,
    changes: Partial<Pick<Account, 'deviceJid' | 'autoConnect' | 'sessionStatus' | 'sessionCompleteness' | 'pairingStatus' | 'pairingExpiresAt' | 'metadataSyncStatus'>>,
    reasonCategory: string,
    providerCode?: string,
    failure?: FailureDiagnosis,
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
        ...(failure ? { failure } : {}),
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

  private async clearRequestedHistory(id: string): Promise<void> {
    const current = await this.store.getAccount(id)
    if (current.metadata.requestContactsHistory !== true) return
    const metadata = { ...current.metadata }
    delete metadata.requestContactsHistory
    await this.store.updateAccount(id, { metadata })
  }

  private clearIdleDisconnect(id: string): void {
    const timer = this.idleDisconnectTimers.get(id)
    if (timer) clearTimeout(timer)
    this.idleDisconnectTimers.delete(id)
  }

  private scheduleIdleDisconnect(account: Account, graceSeconds?: number): void {
    this.clearIdleDisconnect(account.id)
    if (account.connectionPolicy !== 'on_demand' || !this.engine.isOnline(account.id)) return
    const seconds = graceSeconds ?? account.idleDisconnectSeconds
    const timer = setTimeout(() => {
      this.idleDisconnectTimers.delete(account.id)
      void this.idleDisconnect(account.id).catch((error: unknown) => {
        this.logger.warn({ accountId: account.id, error: safeError(error) }, 'idle_disconnect_failed')
      })
    }, Math.max(0, seconds) * 1_000)
    timer.unref()
    this.idleDisconnectTimers.set(account.id, timer)
  }

  private async idleDisconnect(id: string): Promise<void> {
    if ((this.queueDepth.get(id) ?? 0) > 0) {
      this.scheduleIdleDisconnect(await this.store.getAccount(id))
      return
    }
    const current = await this.store.getAccount(id)
    if (current.connectionPolicy !== 'on_demand' || !this.engine.isOnline(id)) return
    await this.engine.disconnect(id)
    await this.transitionAccount(id, 'linked_offline', { autoConnect: false }, 'idle_disconnect')
  }

  private async syncMetadata(account: Account): Promise<{
    account: Account
    avatar?: AccountAvatar | null
    avatarIncluded: boolean
    resources: AccountResourceSnapshot
  }> {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const quality = await this.engine.getQuality(account.id, account.syncPolicy)
        const { avatar, resources, metadata, ...persistentQuality } = quality
        const mergedMetadata = {
          ...account.metadata,
          ...metadata,
          accountProfile: {
            platformRaw: resources.platformRaw,
            accountType: resources.accountType,
            deviceOs: resources.deviceOs,
          },
          resourceSync: {
            contactsStatus: resources.contactsStatus,
            groupsStatus: resources.groupsStatus,
            contactsComplete: resources.contactsComplete,
            identityMappingComplete: resources.identityMappingComplete,
            uniqueGroupMemberCount: resources.uniqueGroupMemberCount,
            syncedAt: resources.syncedAt,
          },
        }
        const metadataSyncStatus = metadataResourcesComplete(
          account.syncPolicy,
          resources,
        ) ? 'ready' : 'pending'
        const updated = await this.store.updateAccount(account.id, {
          metadataSyncStatus,
          ...persistentQuality,
          metadata: mergedMetadata,
        })
        return {
          account: updated,
          ...(avatar !== undefined ? { avatar } : {}),
          avatarIncluded: avatar !== undefined,
          resources,
        }
      } catch (error) {
        if (attempt === 3 || !this.engine.isOnline(account.id)) {
          await this.store.updateAccount(account.id, { metadataSyncStatus: 'failed' })
          this.logger.warn({ accountId: account.id, error: safeError(error), attempts: attempt }, 'metadata_sync_failed')
          throw new GatewayError('protocol_error', 'unable to synchronize account metadata')
        }
        await new Promise((resolve) => setTimeout(resolve, attempt * 1_000))
      }
    }
    throw new GatewayError('protocol_error', 'unable to synchronize account metadata')
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
    await this.clearRequestedHistory(id)
    return this.transitionAccount(id, 'unpaired', {
      deviceJid: '',
      autoConnect: false,
      sessionStatus: 'none',
      sessionCompleteness: 'none',
      pairingStatus: 'expired',
    }, 'pairing_expired')
  }

  private async processSend(messageId: string, accountId: string, recipient: string, message: OutboundMessage): Promise<void> {
    try {
      const intervalMs = Math.ceil(1_000 / this.sendQps)
      const now = Date.now()
      const allowedAt = Math.max(now, this.nextSendAt.get(accountId) ?? now)
      this.nextSendAt.set(accountId, allowedAt + intervalMs)
      if (allowedAt > now) {
        await new Promise((resolve) => setTimeout(resolve, allowedAt - now))
      }
      const providerMessageId = await this.engine.send(accountId, recipient, message)
      const sent = await this.store.updateMessage(messageId, { providerMessageId, status: 'sent', errorCode: '', sentAt: new Date() })
      this.webhook.deliver(sent)
    } catch (error) {
      const failed = await this.store.updateMessage(messageId, { status: 'failed', errorCode: 'send_failed' })
      this.webhook.deliver(failed)
      this.logger.warn({ messageId, accountId, error: safeError(error) }, 'message_send_failed')
    } finally {
      try { this.scheduleIdleDisconnect(await this.store.getAccount(accountId)) } catch { /* account may have been removed */ }
    }
  }

  private async handleEngineEvent(event: EngineEvent): Promise<void> {
    try {
      if (event.kind === 'proxy_result') {
        this.webhook.deliverProxyHealth({
          event: 'proxy.health',
          eventId: newPublicId('phv'),
          accountId: event.accountId,
          outcome: event.outcome,
          reasonCategory: event.reasonCategory,
          proxyFingerprint: event.proxyFingerprint,
          occurredAt: new Date(),
        })
      } else if (event.kind === 'connected') {
        const current = await this.store.getAccount(event.accountId)
        const completedPairing = current.state === 'pairing' && ['waiting_phone', 'reconnecting'].includes(current.pairingStatus)
        if (completedPairing) this.clearPairingExpiry(event.accountId)
        const connected = await this.transitionAccount(event.accountId, 'online_idle', {
          deviceJid: event.deviceJid || current.deviceJid,
          autoConnect: current.connectionPolicy === 'always_on',
          sessionStatus: 'verified',
          ...(completedPairing ? { pairingStatus: 'verified' as const, pairingExpiresAt: null } : {}),
          metadataSyncStatus: completedPairing ? 'pending' : current.metadataSyncStatus,
        }, 'connected')
        this.scheduleIdleDisconnect(
          connected,
          completedPairing ? current.postVerifyGraceSeconds : undefined,
        )
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
          await this.clearRequestedHistory(event.accountId)
          await this.transitionAccount(event.accountId, 'unpaired', {
            deviceJid: '',
            autoConnect: false,
            sessionStatus: 'none',
            sessionCompleteness: 'none',
            pairingStatus: 'failed',
            pairingExpiresAt: null,
          }, 'pairing_connection_lost', event.providerCode, event.failure)
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
          await this.clearRequestedHistory(event.accountId)
          await this.transitionAccount(
            event.accountId,
            'unpaired',
            { deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'failed', pairingExpiresAt: null },
            'pairing_connection_lost',
            event.providerCode,
            event.failure,
          )
        }
      } else if (event.kind === 'logged_out') {
        this.clearPairingExpiry(event.accountId)
        await this.store.clearAuth(event.accountId)
        await this.clearRequestedHistory(event.accountId)
        await this.transitionAccount(event.accountId, 'unpaired', { deviceJid: '', autoConnect: false, sessionStatus: 'none', sessionCompleteness: 'none', pairingStatus: 'failed', pairingExpiresAt: null }, event.reasonCategory, event.providerCode, event.failure)
      } else if (event.kind === 'reauth_required') {
        this.clearPairingExpiry(event.accountId)
        await this.clearRequestedHistory(event.accountId)
        await this.transitionAccount(event.accountId, 'reauth_required', { autoConnect: false }, event.reasonCategory, event.providerCode, event.failure)
      } else if (event.kind === 'restricted') {
        this.clearPairingExpiry(event.accountId)
        await this.clearRequestedHistory(event.accountId)
        await this.transitionAccount(event.accountId, 'restricted', { autoConnect: false }, event.reasonCategory, event.providerCode, event.failure)
      } else if (event.kind === 'delivered') {
        const message = await this.store.markDeliveredByProvider(event.accountId, event.providerMessageId)
        if (message) this.webhook.deliver(message)
      }
    } catch (error) {
      this.logger.warn({ accountId: event.accountId, kind: event.kind, error: safeError(error) }, 'engine_event_persist_failed')
    }
  }
}
