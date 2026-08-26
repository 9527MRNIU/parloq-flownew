import pino from 'pino'
import { describe, expect, it } from 'vitest'
import { emptyAccountResources, type SyncPolicy } from './domain.js'
import type {
  AccountQuality,
  EngineAccount,
  EngineEvent,
  PairResult,
  ProtocolEngine,
} from './engine.js'
import type { OutboundMessage } from './message-content.js'
import type { Store } from './store.js'
import { VersionedProtocolEngine } from './versioned-engine.js'

class RecordingRuntime implements ProtocolEngine {
  readonly name = 'baileys'
  readonly calls: string[] = []
  private handler: (event: EngineEvent) => void = () => undefined

  constructor(readonly key: string) {}
  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }
  async start(): Promise<void> { this.calls.push('start') }
  async ready(): Promise<void> {}
  async close(): Promise<void> { this.calls.push('close') }
  async pair(account: EngineAccount): Promise<PairResult> {
    this.calls.push(`pair:${account.accountId}`)
    return { accountId: account.accountId, code: '1234-5678', expiresAt: new Date() }
  }
  async connect(account: EngineAccount): Promise<void> {
    this.calls.push(`connect:${account.accountId}`)
    this.handler({ kind: 'connected', accountId: account.accountId, deviceJid: '' })
  }
  async disconnect(accountId: string): Promise<void> { this.calls.push(`disconnect:${accountId}`) }
  async logout(account: EngineAccount): Promise<void> { this.calls.push(`logout:${account.accountId}`) }
  async send(accountId: string, _toE164: string, _message: OutboundMessage): Promise<string> {
    this.calls.push(`send:${accountId}`)
    return `${this.key}:${accountId}`
  }
  async getQuality(accountId: string, _policy: SyncPolicy): Promise<AccountQuality> {
    this.calls.push(`quality:${accountId}`)
    return { hasAvatar: null, groupCount: null, friendCount: null, metadata: {}, resources: emptyAccountResources() }
  }
  isOnline(): boolean { return false }
}

const policy: SyncPolicy = {
  closeOnline: true,
  avatar: true,
  groupDetails: true,
  contacts: true,
}

function account(accountId: string, definitionId: string, version: string): EngineAccount {
  return {
    accountId,
    protocolDefinitionId: definitionId,
    protocolVersion: version,
    phoneE164: '+12025550199',
    proxyUrl: 'socks5://proxy:1080',
    syncPolicy: policy,
  }
}

describe('VersionedProtocolEngine', () => {
  it('keeps accounts pinned to separate protocol runtimes', async () => {
    const runtimes = new Map<string, RecordingRuntime>()
    const engine = new VersionedProtocolEngine(
      { listAccounts: async () => [] } as unknown as Store,
      pino({ enabled: false }),
      (binding) => {
        const key = `${binding.definitionId}:${binding.version}`
        const runtime = new RecordingRuntime(key)
        runtimes.set(key, runtime)
        return runtime
      },
    )
    await engine.start()
    await engine.connect(account('account-a', '101', '6.7.24'))
    await engine.connect(account('account-b', '202', '7.0.0-rc.14'))

    expect(await engine.send('account-a', '+12025550200', { version: 1, header: { type: 'none' }, body: { text: 'a' }, footer: { text: '' }, buttons: [] }))
      .toBe('101:6.7.24:account-a')
    expect(await engine.send('account-b', '+12025550200', { version: 1, header: { type: 'none' }, body: { text: 'b' }, footer: { text: '' }, buttons: [] }))
      .toBe('202:7.0.0-rc.14:account-b')
    expect(runtimes.get('101:6.7.24')?.calls).not.toContain('send:account-b')
    expect(runtimes.get('202:7.0.0-rc.14')?.calls).not.toContain('send:account-a')
  })
})
