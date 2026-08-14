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

export interface Account {
  id: string
  phoneE164: string
  proxyUrl: string
  state: AccountState
  deviceJid: string
  autoConnect: boolean
  sessionStatus: SessionStatus
  sessionCompleteness: SessionCompleteness
  pairingStatus: PairingStatus
  pairingExpiresAt: Date | null
  metadataSyncStatus: 'pending' | 'syncing' | 'ready' | 'failed' | 'unsupported'
  hasAvatar: boolean | null
  groupCount: number | null
  friendCount: number | null
  mutualContactCount: number | null
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
