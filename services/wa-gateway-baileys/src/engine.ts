import { Boom } from '@hapi/boom'
import * as BuiltinBaileys from '@whiskeysockets/baileys'
import type {
  Chat,
  Contact,
  proto,
  ConnectionState,
  GroupMetadata,
  WASocket,
  WAMessage,
} from '@whiskeysockets/baileys'
import { get as httpsGet, type Agent } from 'node:https'
import { createHash } from 'node:crypto'
import pino, { type Logger } from 'pino'
import { ProxyAgent } from 'proxy-agent'
import { loadAuthState, mergeCreds, type BaileysRuntimeModule } from './auth-store.js'
import type { Store } from './store.js'
import { WaWebVersionResolver } from './wa-version.js'
import type { ManagedMediaReference, MessageButton, OutboundMessage } from './message-content.js'
import type {
  AccountAvatar,
  AccountResourceSnapshot,
  ResourceSyncStatus,
  SyncedContact,
  SyncedGroup,
  SyncPolicy,
} from './domain.js'
import { emptyAccountResources } from './domain.js'
import { classifyProxyFailure, proxyFingerprint } from './proxy-health.js'
import { diagnosePairingFailure } from './failure-diagnosis.js'
import type { FailureDiagnosis } from './domain.js'

export type EngineEvent =
  | { kind: 'connected'; accountId: string; deviceJid: string }
  | { kind: 'proxy_result'; accountId: string; outcome: 'success' | 'failure'; reasonCategory: string; proxyFingerprint: string }
  | { kind: 'pairing_restarting'; accountId: string; reasonCategory: string; providerCode?: string; failure?: FailureDiagnosis }
  | { kind: 'disconnected' | 'logged_out' | 'reauth_required' | 'restricted'; accountId: string; reasonCategory: string; providerCode?: string; failure?: FailureDiagnosis }
  | { kind: 'delivered'; accountId: string; providerMessageId: string }

export interface PairResult { accountId: string; code: string; expiresAt: Date; deviceJid?: string }
export const PAIRING_CODE_TTL_MS = 150_000
export interface EngineAccount {
  accountId: string
  protocolDefinitionId: string
  protocolVersion: string
  phoneE164: string
  proxyUrl: string
  syncPolicy: SyncPolicy
  customPairingCode?: string
  metadata?: Record<string, unknown>
}
export interface AccountQuality {
  hasAvatar: boolean | null
  avatar?: AccountAvatar | null
  groupCount: number | null
  friendCount: number | null
  metadata: Record<string, unknown>
  resources: AccountResourceSnapshot
}

const MAX_PROFILE_AVATAR_BYTES = 2 * 1024 * 1024
const PROFILE_AVATAR_TIMEOUT_MS = 15_000
const MAX_PROFILE_AVATAR_REDIRECTS = 3

function detectedAvatarContentType(content: Buffer): string | null {
  if (content.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))) return 'image/jpeg'
  if (content.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'image/png'
  if (content.length >= 12 && content.subarray(0, 4).toString() === 'RIFF' && content.subarray(8, 12).toString() === 'WEBP') return 'image/webp'
  if (content.length >= 12 && content.subarray(4, 8).toString() === 'ftyp' && ['avif', 'avis'].includes(content.subarray(8, 12).toString())) return 'image/avif'
  return null
}

export interface DownloadedProfileAvatar {
  contentType: string
  size: number
  sha256: string
  dataBase64: string
}

export type ProfileAvatarDownloader = (
  url: string,
  agent?: Agent,
) => Promise<DownloadedProfileAvatar>

export async function downloadProfileAvatar(
  url: string,
  agent?: Agent,
  redirects = 0,
): Promise<DownloadedProfileAvatar> {
  const target = new URL(url)
  if (target.protocol !== 'https:' || !target.hostname || target.href.length > 4096) {
    throw new Error('profile avatar URL is invalid')
  }
  return new Promise((resolve, reject) => {
    const request = httpsGet(target, { agent }, (response) => {
      const status = response.statusCode ?? 0
      const location = response.headers.location
      if (status >= 300 && status < 400 && location) {
        response.resume()
        if (redirects >= MAX_PROFILE_AVATAR_REDIRECTS) {
          reject(new Error('profile avatar redirected too many times'))
          return
        }
        void downloadProfileAvatar(new URL(location, target).toString(), agent, redirects + 1)
          .then(resolve, reject)
        return
      }
      if (status !== 200) {
        response.resume()
        reject(new Error(`profile avatar download failed (${status})`))
        return
      }
      const declaredLength = Number(response.headers['content-length'] || 0)
      if (declaredLength > MAX_PROFILE_AVATAR_BYTES) {
        response.resume()
        reject(new Error('profile avatar is too large'))
        return
      }
      const chunks: Buffer[] = []
      let size = 0
      response.on('data', (chunk: Buffer) => {
        size += chunk.length
        if (size > MAX_PROFILE_AVATAR_BYTES) {
          response.destroy(new Error('profile avatar is too large'))
          return
        }
        chunks.push(chunk)
      })
      response.on('error', reject)
      response.on('end', () => {
        const content = Buffer.concat(chunks)
        const contentType = detectedAvatarContentType(content)
        const declaredType = (String(response.headers['content-type'] || '')
          .split(';', 1)[0] ?? '')
          .trim()
          .toLowerCase()
        if (!content.length || !contentType || (declaredType && declaredType !== contentType)) {
          reject(new Error('profile avatar content is not a supported image'))
          return
        }
        resolve({
          contentType,
          size: content.length,
          sha256: createHash('sha256').update(content).digest('hex'),
          dataBase64: content.toString('base64'),
        })
      })
    })
    request.setTimeout(PROFILE_AVATAR_TIMEOUT_MS, () => {
      request.destroy(new Error('profile avatar download timed out'))
    })
    request.on('error', reject)
  })
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

export function messageTargetJid(target: string): string {
  return target.endsWith('@g.us') || target.endsWith('@s.whatsapp.net')
    ? target
    : `${target.slice(1)}@s.whatsapp.net`
}

interface ActiveSocket {
  socket: WASocket
  online: boolean
  resources: ResourceAccumulator
  intentionalClose?: boolean
  proxyAgent?: ProxyAgent
  proxyFailureReported?: boolean
}

interface ResourceAccumulator {
  contacts: Map<string, SyncedContact>
  aliases: Map<string, string>
  groupLastInteractionAt: Map<string, string>
  historyRequested: boolean
  historyReceived: boolean
  historyComplete: boolean
  historyWaiters: Set<() => void>
  platformRaw: string | null
}

const CONTACT_SOURCE_SAVED = 1
const CONTACT_SOURCE_HISTORY = 2
const CONTACT_SOURCE_MESSAGE = 4
const CONTACT_SOURCE_REALTIME = 8
const MAX_TRANSIENT_RECONNECT_ATTEMPTS = 6

function nullableString(value: unknown, maxLength = 512): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized ? normalized.slice(0, maxLength) : null
}

function phoneFromJid(value: string | null | undefined): string | null {
  if (!value?.endsWith('@s.whatsapp.net')) return null
  const digits = value.split('@', 1)[0]?.split(':', 1)[0]
  return digits && /^\d{7,15}$/.test(digits) ? `+${digits}` : null
}

function latestTimestamp(first: string | null, second: string | null): string | null {
  if (!first) return second
  if (!second) return first
  return first >= second ? first : second
}

function unixTimestamp(raw: unknown): string | null {
  if (raw == null) return null
  const seconds = Number(raw)
  if (!Number.isFinite(seconds) || seconds <= 0) return null
  return new Date(seconds * 1_000).toISOString()
}

function messageTimestamp(value: WAMessage): string | null {
  return unixTimestamp(value.messageTimestamp)
}

function recordGroupInteraction(
  accumulator: ResourceAccumulator,
  groupJid: string | null,
  timestamp: string | null,
): void {
  if (!groupJid?.endsWith('@g.us') || !timestamp) return
  const existing = accumulator.groupLastInteractionAt.get(groupJid) ?? null
  accumulator.groupLastInteractionAt.set(
    groupJid,
    latestTimestamp(existing, timestamp)!,
  )
}

function groupInteractionFromChat(
  accumulator: ResourceAccumulator,
  chat: Chat,
): void {
  const groupJid = nullableString(chat.id, 191)
  const timestamp = [
    chat.conversationTimestamp,
    chat.lastMsgTimestamp,
    chat.lastMessageRecvTimestamp,
  ].reduce<string | null>(
    (latest, value) => latestTimestamp(latest, unixTimestamp(value)),
    null,
  )
  recordGroupInteraction(accumulator, groupJid, timestamp)
}

function groupInteractionFromMessage(
  accumulator: ResourceAccumulator,
  message: WAMessage,
): void {
  recordGroupInteraction(
    accumulator,
    nullableString(message.key.remoteJid, 191),
    messageTimestamp(message),
  )
}

function normalizePlatform(platform: string | null): {
  platformRaw: string | null
  accountType: 'personal' | 'business' | 'unknown'
  deviceOs: 'android' | 'ios' | 'other' | 'unknown'
} {
  const platformRaw = nullableString(platform, 32)?.toLowerCase() ?? null
  if (!platformRaw) return { platformRaw: null, accountType: 'unknown', deviceOs: 'unknown' }
  if (platformRaw === 'smba') return { platformRaw, accountType: 'business', deviceOs: 'android' }
  if (platformRaw === 'smbi') return { platformRaw, accountType: 'business', deviceOs: 'ios' }
  if (['android', 'android_phone', 'android_tablet'].includes(platformRaw)) {
    return { platformRaw, accountType: 'personal', deviceOs: 'android' }
  }
  if (['iphone', 'ios', 'ipad'].includes(platformRaw)) {
    return { platformRaw, accountType: 'personal', deviceOs: 'ios' }
  }
  return { platformRaw, accountType: 'unknown', deviceOs: 'other' }
}

function mergeContact(
  accumulator: ResourceAccumulator,
  value: Partial<Contact> & { id?: string },
  options: {
    sourceMask: number
    hasChatHistory?: boolean
    lastInteractionAt?: string | null
  },
): void {
  const rawId = nullableString(value.id, 191)
  const jid = nullableString(value.jid, 191) ?? (rawId?.endsWith('@s.whatsapp.net') ? rawId : null)
  const lid = nullableString(value.lid, 191) ?? (rawId?.endsWith('@lid') ? rawId : null)
  const identities = [...new Set([rawId, jid, lid].filter((item): item is string => Boolean(item)))]
  if (!identities.length) return

  const matchedIds = new Set(
    identities
      .map((identity) => accumulator.aliases.get(identity))
      .filter((identity): identity is string => Boolean(identity)),
  )
  const preferredId = jid ?? [...matchedIds][0] ?? lid ?? rawId!
  let merged: SyncedContact = {
    contactId: preferredId,
    jid: null,
    lid: null,
    phoneE164: null,
    savedName: null,
    notifyName: null,
    verifiedName: null,
    imageState: null,
    profileStatus: null,
    sourceMask: 0,
    isSavedContact: false,
    hasChatHistory: false,
    lastInteractionAt: null,
  }
  for (const matchedId of matchedIds) {
    const existing = accumulator.contacts.get(matchedId)
    if (!existing) continue
    merged = {
      ...merged,
      ...existing,
      contactId: preferredId,
      jid: merged.jid ?? existing.jid,
      lid: merged.lid ?? existing.lid,
      phoneE164: merged.phoneE164 ?? existing.phoneE164,
      savedName: merged.savedName ?? existing.savedName,
      notifyName: merged.notifyName ?? existing.notifyName,
      verifiedName: merged.verifiedName ?? existing.verifiedName,
      imageState: merged.imageState ?? existing.imageState,
      profileStatus: merged.profileStatus ?? existing.profileStatus,
      sourceMask: merged.sourceMask | existing.sourceMask,
      isSavedContact: merged.isSavedContact || existing.isSavedContact,
      hasChatHistory: merged.hasChatHistory || existing.hasChatHistory,
      lastInteractionAt: latestTimestamp(merged.lastInteractionAt, existing.lastInteractionAt),
    }
    accumulator.contacts.delete(matchedId)
    for (const [alias, target] of accumulator.aliases) {
      if (target === matchedId) accumulator.aliases.set(alias, preferredId)
    }
  }

  const savedName = nullableString(value.name, 255)
  merged = {
    ...merged,
    contactId: preferredId,
    jid: jid ?? merged.jid,
    lid: lid ?? merged.lid,
    phoneE164: phoneFromJid(jid) ?? merged.phoneE164,
    savedName: savedName ?? merged.savedName,
    notifyName: nullableString(value.notify, 255) ?? merged.notifyName,
    verifiedName: nullableString(value.verifiedName, 255) ?? merged.verifiedName,
    imageState: value.imgUrl === null ? 'none' : nullableString(value.imgUrl, 255) ?? merged.imageState,
    profileStatus: nullableString(value.status, 512) ?? merged.profileStatus,
    sourceMask: merged.sourceMask | options.sourceMask,
    isSavedContact: merged.isSavedContact || Boolean(savedName),
    hasChatHistory: merged.hasChatHistory || options.hasChatHistory === true,
    lastInteractionAt: latestTimestamp(
      merged.lastInteractionAt,
      options.lastInteractionAt ?? null,
    ),
  }
  accumulator.contacts.set(preferredId, merged)
  for (const identity of [...identities, preferredId]) accumulator.aliases.set(identity, preferredId)
}

function registerPhoneShare(accumulator: ResourceAccumulator, lid: string, jid: string): void {
  mergeContact(accumulator, { id: jid, jid, lid }, { sourceMask: CONTACT_SOURCE_HISTORY })
}

function contactFromMessage(
  accumulator: ResourceAccumulator,
  message: WAMessage,
  realtime: boolean,
  baileys: BaileysRuntimeModule,
): void {
  const remoteJid = nullableString(message.key.remoteJid, 191)
  if (!remoteJid || (!baileys.isJidUser(remoteJid) && !baileys.isLidUser(remoteJid))) return
  const participantJid = nullableString(message.key.senderPn, 191)
  const participantLid = nullableString(message.key.senderLid, 191)
  mergeContact(
    accumulator,
    {
      id: remoteJid,
      ...(remoteJid.endsWith('@s.whatsapp.net') || participantJid
        ? { jid: remoteJid.endsWith('@s.whatsapp.net') ? remoteJid : participantJid! }
        : {}),
      ...(remoteJid.endsWith('@lid') || participantLid
        ? { lid: remoteJid.endsWith('@lid') ? remoteJid : participantLid! }
        : {}),
      ...(nullableString(message.pushName, 255)
        ? { notify: nullableString(message.pushName, 255)! }
        : {}),
    },
    {
      sourceMask: CONTACT_SOURCE_MESSAGE | (realtime ? CONTACT_SOURCE_REALTIME : 0),
      hasChatHistory: true,
      lastInteractionAt: messageTimestamp(message),
    },
  )
}

function resolveHistoryWaiters(accumulator: ResourceAccumulator): void {
  for (const resolve of accumulator.historyWaiters) resolve()
  accumulator.historyWaiters.clear()
}

async function waitForHistory(accumulator: ResourceAccumulator): Promise<void> {
  if (!accumulator.historyRequested || accumulator.historyComplete) return
  await Promise.race([
    new Promise<void>((resolve) => accumulator.historyWaiters.add(resolve)),
    new Promise<void>((resolve) => setTimeout(resolve, 8_000)),
  ])
}

function sameIdentity(
  left: string | null | undefined,
  right: string | null | undefined,
  baileys: BaileysRuntimeModule,
): boolean {
  if (!left || !right) return false
  return left === right || baileys.areJidsSameUser(left, right)
}

function groupResources(
  groups: GroupMetadata[],
  ownJid: string | undefined,
  accumulator: ResourceAccumulator,
  baileys: BaileysRuntimeModule,
): {
  groups: SyncedGroup[]
  uniqueGroupMemberCount: number
  identityMappingComplete: boolean
} {
  const uniqueMembers = new Set<string>()
  let identityMappingComplete = true
  const resources = groups.map((group): SyncedGroup => {
    const own = group.participants.find((participant) =>
      [participant.id, participant.jid, participant.lid].some((identity) =>
        sameIdentity(identity, ownJid, baileys),
      ),
    )
    const ownRole: SyncedGroup['ownRole'] = own?.isSuperAdmin || own?.admin === 'superadmin'
      ? 'superadmin'
      : own?.isAdmin || own?.admin === 'admin'
        ? 'admin'
        : 'member'
    for (const participant of group.participants) {
      const identities = [participant.jid, participant.id, participant.lid]
        .filter((identity): identity is string => Boolean(identity))
      if (identities.some((identity) => sameIdentity(identity, ownJid, baileys))) continue
      const phoneJid = identities.find((identity) => identity.endsWith('@s.whatsapp.net'))
      const mapped = identities
        .map((identity) => accumulator.aliases.get(identity))
        .find((identity): identity is string => Boolean(identity))
      const canonical = phoneJid ?? mapped ?? identities[0]
      if (!canonical) continue
      if (!phoneJid && canonical.endsWith('@lid')) identityMappingComplete = false
      uniqueMembers.add(canonical)
    }
    const communityType: SyncedGroup['communityType'] = group.isCommunityAnnounce
      ? 'community_announcement'
      : group.isCommunity
        ? 'community'
        : 'group'
    return {
      groupJid: group.id,
      subject: group.subject || '',
      size: Math.max(0, Number(group.size ?? group.participants.length) || 0),
      announce: group.announce === true,
      restrict: group.restrict === true,
      communityType,
      addressingMode: group.addressingMode ?? null,
      linkedParentJid: group.linkedParent ?? null,
      ownRole,
      canSend: group.announce !== true || ownRole !== 'member',
      lastInteractionAt: accumulator.groupLastInteractionAt.get(group.id) ?? null,
    }
  })
  return {
    groups: resources,
    uniqueGroupMemberCount: uniqueMembers.size,
    identityMappingComplete,
  }
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
  customPairingCode?: string,
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
      customPairingCode
        ? socket.requestPairingCode(phone, customPairingCode)
        : socket.requestPairingCode(phone),
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
  private currentWaWebVersion: string | null = null

  constructor(
    private readonly store: Store,
    logger?: Logger,
    private readonly materialBaseUrl = 'http://api:8000',
    private readonly baileys: BaileysRuntimeModule = BuiltinBaileys,
    private readonly avatarDownloader: ProfileAvatarDownloader = downloadProfileAvatar,
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
    const code = await requestStablePairingCode(
      active.socket,
      phone,
      20_000,
      250,
      account.customPairingCode,
    )
    return { accountId: account.accountId, code, expiresAt: new Date(issuedAt + PAIRING_CODE_TTL_MS) }
  }

  async connect(account: EngineAccount): Promise<void> {
    if (this.isOnline(account.accountId)) return
    // A user or service initiated connect starts a new bounded retry cycle.
    this.reconnectAttempts.delete(account.accountId)
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
    active.intentionalClose = true
    resolveHistoryWaiters(active.resources)
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
    const jid = messageTargetJid(toE164)
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
    if (policy.contacts || policy.groupDetails) await waitForHistory(active.resources)
    let hasAvatar: boolean | null = null
    let avatar: AccountAvatar | null | undefined
    if (policy.avatar && ownJid) {
      try {
        const sourceUrl = await active.socket.profilePictureUrl(ownJid, 'image')
        hasAvatar = Boolean(sourceUrl)
        avatar = sourceUrl ? { sourceUrl } : null
        if (sourceUrl) {
          try {
            avatar = {
              sourceUrl,
              ...await this.avatarDownloader(sourceUrl, active.proxyAgent),
            }
          } catch (error) {
            this.protocolLogger.warn(
              { accountId, error: error instanceof Error ? error.message : String(error) },
              'profile_avatar_download_failed',
            )
          }
        }
      } catch (error) {
        const statusCode = new Boom(error instanceof Error ? error : String(error)).output.statusCode
        if (statusCode === 404) {
          hasAvatar = false
          avatar = null
        }
      }
    }
    let groupCount: number | null = null
    let groups: SyncedGroup[] = []
    let groupsStatus: ResourceSyncStatus = policy.groupDetails ? 'pending' : 'disabled'
    let uniqueGroupMemberCount: number | null = null
    let identityMappingComplete = true
    const metadata: Record<string, unknown> = {}
    if (policy.groupDetails) {
      try {
        const participating = Object.values(await active.socket.groupFetchAllParticipating())
        const normalized = groupResources(
          participating,
          ownJid,
          active.resources,
          this.baileys,
        )
        groups = normalized.groups
        groupCount = groups.length
        uniqueGroupMemberCount = normalized.uniqueGroupMemberCount
        identityMappingComplete = normalized.identityMappingComplete
        groupsStatus = 'complete'
        metadata.groups = groups.map((group) => ({
          id: group.groupJid,
          subject: group.subject,
          size: group.size,
        }))
      } catch {
        groupCount = null
        groupsStatus = 'failed'
      }
    }
    const contacts = policy.contacts
      ? [...active.resources.contacts.values()].filter(
          (contact) => contact.isSavedContact || contact.hasChatHistory,
        )
      : []
    const contactsStatus: ResourceSyncStatus = !policy.contacts
      ? 'disabled'
      : active.resources.historyComplete
        ? 'complete'
        : active.resources.historyReceived || contacts.length
          ? 'partial'
          : 'pending'
    const platform = normalizePlatform(active.resources.platformRaw)
    return {
      hasAvatar,
      ...(avatar !== undefined ? { avatar } : {}),
      groupCount,
      friendCount: policy.contacts ? contacts.length : null,
      metadata,
      resources: {
        contacts,
        groups,
        contactsStatus,
        groupsStatus,
        contactsComplete: active.resources.historyComplete,
        identityMappingComplete,
        uniqueGroupMemberCount,
        ...platform,
        syncedAt: new Date().toISOString(),
      },
    }
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
    const historyRequested = (account.syncPolicy.contacts || account.syncPolicy.groupDetails)
      && account.metadata?.requestContactsHistory === true
    const socket = this.baileys.default({
      auth: state,
      browser: this.baileys.Browsers.macOS('Chrome'),
      version,
      logger: this.protocolLogger,
      markOnlineOnConnect: !account.syncPolicy.closeOnline,
      syncFullHistory: historyRequested,
      shouldSyncHistoryMessage: () => historyRequested,
      ...(proxyAgent ? { agent: proxyAgent as Agent, fetchAgent: proxyAgent as Agent } : {}),
    })
    const resources: ResourceAccumulator = {
      contacts: new Map(),
      aliases: new Map(),
      groupLastInteractionAt: new Map(),
      historyRequested,
      historyReceived: false,
      historyComplete: false,
      historyWaiters: new Set(),
      platformRaw: nullableString(state.creds.platform, 32),
    }
    const active: ActiveSocket = proxyAgent
      ? { socket, online: false, proxyAgent, resources }
      : { socket, online: false, resources }
    this.sockets.set(account.accountId, active)

    let credsSaveTail = Promise.resolve()
    let pairingConfigured = false
    socket.ev.on('creds.update', (update) => {
      mergeCreds(state.creds, update)
      if (typeof update.platform === 'string') {
        active.resources.platformRaw = nullableString(update.platform, 32)
      }
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
        resolveHistoryWaiters(active.resources)
        if (this.sockets.get(account.accountId) === active) this.sockets.delete(account.accountId)
        proxyAgent?.destroy()
        if (active.intentionalClose) return
        const disconnectError = update.lastDisconnect?.error
        this.reportProxyFailure(account, active, disconnectError)
        const statusCode = disconnectError instanceof Boom
          ? disconnectError.output.statusCode
          : new Boom(disconnectError).output.statusCode
        const providerCode = String(statusCode)
        const failure = diagnosePairingFailure(disconnectError, {
          stage: createAuth ? 'wait_pair_success' : 'connection',
          protocolCode: providerCode,
        })
        if (statusCode === this.baileys.DisconnectReason.loggedOut) {
          void this.store.clearAuth(account.accountId)
          this.handler({ kind: 'logged_out', accountId: account.accountId, reasonCategory: 'logged_out', providerCode, failure })
        } else if (statusCode === this.baileys.DisconnectReason.forbidden) {
          this.handler({ kind: 'restricted', accountId: account.accountId, reasonCategory: 'restricted', providerCode, failure })
        } else if ([this.baileys.DisconnectReason.badSession, this.baileys.DisconnectReason.multideviceMismatch].includes(statusCode)) {
          this.handler({
            kind: 'reauth_required',
            accountId: account.accountId,
            reasonCategory: statusCode === this.baileys.DisconnectReason.badSession ? 'bad_session' : 'multidevice_mismatch',
            providerCode,
            failure,
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
              failure,
            })
          } else if (!this.blockedReconnect.has(account.accountId)) {
            this.handler({
              kind: 'disconnected',
              accountId: account.accountId,
              reasonCategory: transient ? 'connection_lost' : 'protocol_disconnect',
              providerCode,
              failure,
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
    socket.ev.on('messaging-history.set', ({ chats, contacts, messages, isLatest, progress }) => {
      if (!account.syncPolicy.contacts && !account.syncPolicy.groupDetails) return
      active.resources.historyReceived = true
      if (account.syncPolicy.groupDetails) {
        for (const chat of chats ?? []) groupInteractionFromChat(active.resources, chat)
      }
      for (const message of messages) {
        if (account.syncPolicy.groupDetails) {
          groupInteractionFromMessage(active.resources, message)
        }
        if (account.syncPolicy.contacts) {
          contactFromMessage(active.resources, message, false, this.baileys)
        }
      }
      if (account.syncPolicy.contacts) {
        for (const contact of contacts) {
          mergeContact(active.resources, contact, { sourceMask: CONTACT_SOURCE_HISTORY })
        }
      }
      if (isLatest === true || Number(progress) >= 100) {
        active.resources.historyComplete = true
        resolveHistoryWaiters(active.resources)
      }
    })
    socket.ev.on('contacts.upsert', (contacts) => {
      if (!account.syncPolicy.contacts) return
      for (const contact of contacts) {
        mergeContact(active.resources, contact, {
          sourceMask: CONTACT_SOURCE_SAVED | CONTACT_SOURCE_REALTIME,
        })
      }
    })
    socket.ev.on('contacts.update', (contacts) => {
      if (!account.syncPolicy.contacts) return
      for (const contact of contacts) {
        mergeContact(active.resources, contact, {
          sourceMask: CONTACT_SOURCE_REALTIME,
        })
      }
    })
    socket.ev.on('chats.phoneNumberShare', ({ lid, jid }) => {
      if (!account.syncPolicy.contacts) return
      registerPhoneShare(active.resources, lid, jid)
    })
    socket.ev.on('messages.upsert', ({ messages }) => {
      if (!account.syncPolicy.contacts && !account.syncPolicy.groupDetails) return
      for (const message of messages) {
        if (account.syncPolicy.groupDetails) {
          groupInteractionFromMessage(active.resources, message)
        }
        if (account.syncPolicy.contacts) {
          contactFromMessage(active.resources, message, true, this.baileys)
        }
      }
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
    if (attempt > MAX_TRANSIENT_RECONNECT_ATTEMPTS) {
      this.reconnectAttempts.delete(account.accountId)
      this.blockedReconnect.add(account.accountId)
      this.protocolLogger.warn(
        { accountId: account.accountId, attempts: MAX_TRANSIENT_RECONNECT_ATTEMPTS },
        'transient_reconnect_exhausted',
      )
      return
    }
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
    return { accountId: account.accountId, code: account.customPairingCode || '0000-0000', expiresAt: new Date(Date.now() + PAIRING_CODE_TTL_MS), deviceJid: `mock-${account.accountId}@s.whatsapp.net` }
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
    return {
      hasAvatar: null,
      groupCount: null,
      friendCount: null,
      metadata: {},
      resources: emptyAccountResources(),
    }
  }
}
