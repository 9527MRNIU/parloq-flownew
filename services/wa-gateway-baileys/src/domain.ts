export const accountStates = [
  'unpaired',
  'pairing',
  'linked_offline',
  'warming',
  'online_idle',
  'sending',
  'reauth_required',
  'restricted',
] as const

export type AccountState = (typeof accountStates)[number]
export type SessionStatus = 'none' | 'pending_verification' | 'verified'
export type SessionCompleteness = 'none' | 'credentials_only' | 'full'
export type PairingStatus = 'idle' | 'waiting_phone' | 'reconnecting' | 'verified' | 'expired' | 'cancelled' | 'failed'
export type MessageStatus = 'queued' | 'sent' | 'delivered' | 'failed'

export interface SyncPolicy {
  closeOnline: boolean
  avatar: boolean
  groupSummary: boolean
  groupDetails: boolean
  contacts: boolean
  chats: boolean
  messageHistory: boolean
}

export const defaultSyncPolicy: SyncPolicy = {
  closeOnline: true,
  avatar: true,
  groupSummary: true,
  groupDetails: false,
  contacts: false,
  chats: false,
  messageHistory: false,
}

export interface AccountAvatar {
  sourceUrl: string
  contentType?: string
  size?: number
  sha256?: string
  dataBase64?: string
}

export function normalizeSyncPolicy(value: unknown): SyncPolicy {
  const input = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const result = { ...defaultSyncPolicy }
  for (const key of Object.keys(result) as Array<keyof SyncPolicy>) {
    if (typeof input[key] === 'boolean') result[key] = input[key]
  }
  if (result.groupDetails) result.groupSummary = true
  return result
}

export interface Account {
  id: string
  protocolDefinitionId: string
  protocolVersion: string
  phoneE164: string
  proxyUrl: string
  state: AccountState
  deviceJid: string
  autoConnect: boolean
  connectionPolicy: 'on_demand' | 'always_on'
  idleDisconnectSeconds: number
  postVerifyGraceSeconds: number
  syncPolicy: SyncPolicy
  sessionStatus: SessionStatus
  sessionCompleteness: SessionCompleteness
  pairingStatus: PairingStatus
  pairingExpiresAt: Date | null
  metadataSyncStatus: 'pending' | 'syncing' | 'ready' | 'failed' | 'unsupported'
  hasAvatar: boolean | null
  groupCount: number | null
  friendCount: number | null
  mutualContactCount: number | null
  metadata: Record<string, unknown>
  stateChangedAt: Date
  invalidatedAt: Date | null
  reasonCategory: string
  providerCode: string | null
  createdAt: Date
  updatedAt: Date
}

export interface AccountStateTransition {
  account: Account
  fromState: AccountState
  changed: boolean
}

export interface AccountStateWebhookEvent {
  event: 'account.state'
  eventId: string
  accountId: string
  fromState: AccountState
  toState: AccountState
  reasonCategory: string
  providerCode?: string
  failure?: FailureDiagnosis
  occurredAt: Date
}

export interface FailureDiagnosis {
  code: string
  title: string
  message: string
  suggestion: string
  stage: string
  retryable: boolean
  protocolCode?: string
  technicalMessage?: string
}

export interface ProxyHealthWebhookEvent {
  event: 'proxy.health'
  eventId: string
  accountId: string
  outcome: 'success' | 'failure'
  reasonCategory: string
  proxyFingerprint: string
  occurredAt: Date
}

export interface PublicAccount extends Omit<Account, 'proxyUrl'> {
  proxy: string
  quality: {
    hasAvatar: boolean | null
    groupCount: number | null
    friendCount: number | null
    mutualContactCount: number | null
  }
}

export type MetadataSyncResponse = PublicAccount & {
  avatar?: AccountAvatar | null
}

export interface Message {
  messageId: string
  accountId: string
  recipientE164: string
  providerMessageId: string
  status: MessageStatus
  errorCode: string
  queuedAt: Date
  sentAt: Date | null
  deliveredAt: Date | null
  updatedAt: Date
}

export interface StoredAuth {
  creds: unknown
  keys: StoredKey[]
}

export interface StoredKey {
  type: string
  id: string
  value: unknown
}

export class GatewayError extends Error {
  constructor(
    public readonly code:
      | 'not_found'
      | 'invalid_argument'
      | 'conflict'
      | 'account_offline'
      | 'protocol_error'
      | 'queue_full',
    message: string,
    public readonly failure?: FailureDiagnosis,
  ) {
    super(message)
    this.name = 'GatewayError'
  }
}

export function publicAccount(account: Account): PublicAccount {
  const { proxyUrl, ...safe } = account
  return {
    ...safe,
    proxy: maskProxy(proxyUrl),
    quality: {
      hasAvatar: account.hasAvatar,
      groupCount: account.groupCount,
      friendCount: account.friendCount,
      mutualContactCount: account.mutualContactCount,
    },
  }
}

export function maskProxy(raw: string): string {
  if (!raw) return ''
  try {
    const parsed = new URL(raw)
    parsed.username = ''
    parsed.password = ''
    return parsed.toString()
  } catch {
    return 'configured'
  }
}

export function normalizeE164(raw: string): string {
  const trimmed = raw.trim()
  if (!/^\+[1-9]\d{6,14}$/.test(trimmed)) {
    throw new GatewayError('invalid_argument', 'phone number must use E.164 format')
  }
  return trimmed
}

export function validateProxy(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    throw new GatewayError('invalid_argument', 'proxyUrl must be a valid URL')
  }
  if (!['http:', 'https:', 'socks:', 'socks5:', 'socks5h:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new GatewayError('invalid_argument', 'proxyUrl scheme must be http, https, socks5 or socks5h')
  }
  return trimmed
}

export function safeError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  return message.replace(/((?:https?|socks5h?|socks):\/\/)[^@\s/]+@/gi, '$1[REDACTED]@')
}
