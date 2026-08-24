import type { AuthenticationCreds } from '@whiskeysockets/baileys'
import { decode, encodeAuthValue } from './auth-store.js'
import { GatewayError, type SessionCompleteness, type StoredAuth, type StoredKey } from './domain.js'

export const SESSION_FORMAT = 'parloq-baileys-session'
export const SESSION_VERSION = 1
export const BAILEYS_VERSION = '6.7.24'

interface SessionBundle {
  format: typeof SESSION_FORMAT
  version: typeof SESSION_VERSION
  library: { name: '@whiskeysockets/baileys'; version: string }
  exportedAt?: string
  auth: { creds: unknown; keys: StoredKey[] }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateCreds(value: unknown): asserts value is Record<string, unknown> {
  if (!isRecord(value)) throw new GatewayError('invalid_argument', 'session must be a Baileys credentials object or a Parloq session bundle')
  for (const key of ['noiseKey', 'signedIdentityKey', 'signedPreKey', 'advSecretKey', 'registrationId', 'registered']) {
    if (!(key in value)) throw new GatewayError('invalid_argument', `Baileys credentials are missing ${key}`)
  }
  const decoded = decode<AuthenticationCreds>(encodeAuthValue(value))
  if (!decoded.noiseKey?.private || !decoded.noiseKey?.public || !decoded.signedIdentityKey?.private || !decoded.signedPreKey?.keyPair) {
    throw new GatewayError('invalid_argument', 'Baileys credential key material is malformed')
  }
}

export function parseImportedSession(session: unknown): {
  auth: StoredAuth
  completeness: SessionCompleteness
  deviceJid: string
} {
  if (isRecord(session) && session.format === SESSION_FORMAT) {
    if (session.version !== SESSION_VERSION) throw new GatewayError('invalid_argument', 'unsupported Parloq session bundle version')
    if (!isRecord(session.auth) || !Array.isArray(session.auth.keys)) throw new GatewayError('invalid_argument', 'session bundle auth data is malformed')
    validateCreds(session.auth.creds)
    const keys: StoredKey[] = session.auth.keys.map((entry) => {
      if (!isRecord(entry) || typeof entry.type !== 'string' || typeof entry.id !== 'string' || !('value' in entry)) {
        throw new GatewayError('invalid_argument', 'session bundle contains a malformed key entry')
      }
      return { type: entry.type, id: entry.id, value: encodeAuthValue(entry.value) }
    })
    const creds = encodeAuthValue(session.auth.creds)
    return { auth: { creds, keys }, completeness: 'full', deviceJid: extractDeviceJid(session.auth.creds) }
  }
  validateCreds(session)
  return {
    auth: { creds: encodeAuthValue(session), keys: [] },
    completeness: 'credentials_only',
    deviceJid: extractDeviceJid(session),
  }
}

export function exportSession(auth: StoredAuth, libraryVersion = BAILEYS_VERSION): SessionBundle {
  return {
    format: SESSION_FORMAT,
    version: SESSION_VERSION,
    library: { name: '@whiskeysockets/baileys', version: libraryVersion },
    exportedAt: new Date().toISOString(),
    auth,
  }
}

export function phoneFromDeviceJid(deviceJid: string): string {
  const match = /^([1-9]\d{6,14})(?::\d{1,5})?@s\.whatsapp\.net$/.exec(deviceJid)
  if (!match?.[1]) {
    throw new GatewayError('invalid_argument', 'Baileys credentials must contain a valid me.id device JID to create an account')
  }
  return `+${match[1]}`
}

function extractDeviceJid(creds: unknown): string {
  if (!isRecord(creds) || !isRecord(creds.me) || typeof creds.me.id !== 'string') return ''
  return creds.me.id
}
