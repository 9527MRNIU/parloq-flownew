import {
  BufferJSON,
  initAuthCreds,
  proto,
  type AuthenticationCreds,
  type AuthenticationState,
  type SignalDataSet,
  type SignalDataTypeMap,
} from '@whiskeysockets/baileys'
import type { Store } from './store.js'

function encode(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value, (_key, current: unknown) => {
    if (current instanceof Uint8Array) {
      return { type: 'Buffer', data: Buffer.from(current).toString('base64') }
    }
    if (typeof current === 'object' && current !== null && 'type' in current && 'data' in current && current.type === 'Buffer') {
      if (typeof current.data === 'string') {
        return { type: 'Buffer', data: Buffer.from(current.data, 'base64').toString('base64') }
      }
      if (Array.isArray(current.data) && current.data.every((item) => Number.isInteger(item) && item >= 0 && item <= 255)) {
        return { type: 'Buffer', data: Buffer.from(current.data).toString('base64') }
      }
    }
    return current
  })) as unknown
}

export function decode<T>(value: unknown): T {
  return JSON.parse(JSON.stringify(value), BufferJSON.reviver) as T
}

export async function loadAuthState(store: Store, accountId: string, create: boolean): Promise<{
  state: AuthenticationState
  saveCreds: () => Promise<void>
}> {
  const stored = await store.getCreds(accountId)
  if (stored === null && !create) throw new Error('saved Baileys credentials do not exist')
  const creds = stored === null ? initAuthCreds() : decode<AuthenticationCreds>(stored)
  if (stored === null) await store.setCreds(accountId, encode(creds))

  const state: AuthenticationState = {
    creds,
    keys: {
      get: async <T extends keyof SignalDataTypeMap>(type: T, ids: string[]) => {
        const storedKeys = await store.getKeys(accountId, type, ids)
        const result: { [id: string]: SignalDataTypeMap[T] } = {}
        for (const [id, encodedValue] of Object.entries(storedKeys)) {
          let value = decode<SignalDataTypeMap[T]>(encodedValue)
          if (type === 'app-state-sync-key' && value) {
            value = proto.Message.AppStateSyncKeyData.fromObject(value as unknown as Record<string, unknown>) as unknown as SignalDataTypeMap[T]
          }
          result[id] = value
        }
        return result
      },
      set: async (data: SignalDataSet) => {
        const rows = []
        for (const [type, values] of Object.entries(data)) {
          if (!values) continue
          for (const [id, value] of Object.entries(values)) {
            rows.push({ type, id, value: value === null ? null : encode(value) })
          }
        }
        await store.setKeys(accountId, rows)
      },
      clear: async () => {
        const credsBeforeClear = await store.getCreds(accountId)
        await store.clearAuth(accountId)
        if (credsBeforeClear !== null) await store.setCreds(accountId, credsBeforeClear)
      },
    },
  }
  return { state, saveCreds: async () => store.setCreds(accountId, encode(creds)) }
}

export function encodeAuthValue(value: unknown): unknown { return encode(value) }

export function mergeCreds(base: AuthenticationCreds, update: Partial<AuthenticationCreds>): void {
  Object.assign(base, update)
}
