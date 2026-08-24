import { fork, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import type { Logger } from 'pino'
import type { Account, SyncPolicy } from './domain.js'
import type {
  AccountQuality,
  EngineAccount,
  EngineEvent,
  PairResult,
  ProtocolEngine,
  ProtocolVersionInfo,
} from './engine.js'
import type { OutboundMessage } from './message-content.js'
import { BUILTIN_BAILEYS_VERSION } from './protocol-artifacts.js'
import type { Store } from './store.js'

interface RuntimeBinding {
  definitionId: string
  version: string
}

interface PendingRequest {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: ReturnType<typeof setTimeout>
}

type RuntimeMessage =
  | { kind: 'ready'; definitionId: string; version: string }
  | { kind: 'startup-error'; error: string }
  | { kind: 'event'; event: EngineEvent }
  | { kind: 'response'; id: number; ok: boolean; result?: unknown; error?: string }

export class ProtocolRuntimeProcess implements ProtocolEngine {
  readonly name = 'baileys'
  private child: ChildProcess | null = null
  private startPromise: Promise<void> | null = null
  private nextRequestId = 1
  private readonly pending = new Map<number, PendingRequest>()
  private readonly onlineAccounts = new Set<string>()
  private handler: (event: EngineEvent) => void = () => undefined

  constructor(
    readonly binding: RuntimeBinding,
    private readonly logger: Logger,
  ) {}

  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }

  async start(): Promise<void> {
    if (this.startPromise) return this.startPromise
    this.startPromise = new Promise<void>((resolve, reject) => {
      const runtimePath = fileURLToPath(new URL('./runtime-worker.js', import.meta.url))
      const child = fork(runtimePath, [], {
        env: {
          ...process.env,
          PROTOCOL_DEFINITION_ID: this.binding.definitionId,
          PROTOCOL_VERSION: this.binding.version,
        },
        execArgv: [],
        stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
      })
      this.child = child
      const timer = setTimeout(() => {
        child.kill('SIGKILL')
        reject(new Error('protocol runtime startup timed out'))
      }, 30_000)
      timer.unref()
      const onMessage = (raw: unknown) => {
        const message = raw as RuntimeMessage
        if (message.kind === 'ready') {
          clearTimeout(timer)
          resolve()
          return
        }
        if (message.kind === 'startup-error') {
          clearTimeout(timer)
          reject(new Error(message.error))
          return
        }
        this.handleMessage(message)
      }
      child.on('message', onMessage)
      child.once('exit', (code, signal) => {
        clearTimeout(timer)
        const error = new Error(`protocol runtime exited (${signal ?? code ?? 'unknown'})`)
        if (this.child === child) {
          this.child = null
          this.startPromise = null
        }
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer)
          pending.reject(error)
        }
        this.pending.clear()
        for (const accountId of this.onlineAccounts) {
          this.handler({
            kind: 'disconnected',
            accountId,
            reasonCategory: 'protocol_runtime_exit',
          })
        }
        this.onlineAccounts.clear()
        this.logger.error(
          { definitionId: this.binding.definitionId, version: this.binding.version, code, signal },
          'protocol_runtime_exited',
        )
      })
    })
    try {
      await this.startPromise
    } catch (error) {
      this.startPromise = null
      throw error
    }
  }

  private handleMessage(message: RuntimeMessage): void {
    if (message.kind === 'event') {
      if (message.event.kind === 'connected') this.onlineAccounts.add(message.event.accountId)
      else if (['disconnected', 'logged_out', 'reauth_required', 'restricted'].includes(message.event.kind)) this.onlineAccounts.delete(message.event.accountId)
      this.handler(message.event)
      return
    }
    if (message.kind !== 'response') return
    const pending = this.pending.get(message.id)
    if (!pending) return
    this.pending.delete(message.id)
    clearTimeout(pending.timer)
    if (message.ok) pending.resolve(message.result)
    else pending.reject(new Error(message.error || 'protocol runtime request failed'))
  }

  private async request<T>(method: string, args: unknown[], timeoutMs = 90_000): Promise<T> {
    await this.start()
    const child = this.child
    if (!child?.connected) throw new Error('protocol runtime is unavailable')
    const id = this.nextRequestId++
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`protocol runtime ${method} timed out`))
      }, timeoutMs)
      timer.unref()
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      child.send({ kind: 'command', id, method, args }, (error) => {
        if (!error) return
        const pending = this.pending.get(id)
        if (!pending) return
        this.pending.delete(id)
        clearTimeout(pending.timer)
        pending.reject(error)
      })
    })
  }

  async ready(): Promise<void> { await this.request('ready', [], 15_000) }
  async close(): Promise<void> {
    if (!this.child) return
    try { await this.request('close', [], 20_000) }
    finally { this.child?.kill('SIGTERM'); this.child = null; this.startPromise = null }
  }
  async pair(account: EngineAccount): Promise<PairResult> {
    const value = await this.request<PairResult & { expiresAt: string | Date }>('pair', [account])
    return { ...value, expiresAt: new Date(value.expiresAt) }
  }
  async connect(account: EngineAccount): Promise<void> { await this.request('connect', [account]) }
  async disconnect(accountId: string): Promise<void> {
    await this.request('disconnect', [accountId], 30_000)
    this.onlineAccounts.delete(accountId)
  }
  async logout(account: EngineAccount): Promise<void> {
    await this.request('logout', [account])
    this.onlineAccounts.delete(account.accountId)
  }
  async send(accountId: string, toE164: string, message: OutboundMessage): Promise<string> {
    return this.request('send', [accountId, toE164, message])
  }
  async getQuality(accountId: string, policy: SyncPolicy): Promise<AccountQuality> {
    return this.request('getQuality', [accountId, policy], 120_000)
  }
  isOnline(accountId: string): boolean { return this.onlineAccounts.has(accountId) }
  async protocolVersionInfo(): Promise<ProtocolVersionInfo> {
    return this.request('protocolVersionInfo', [], 30_000)
  }
}

type RuntimeFactory = (binding: RuntimeBinding) => ProtocolEngine

export class VersionedProtocolEngine implements ProtocolEngine {
  readonly name = 'baileys'
  private readonly runtimes = new Map<string, ProtocolEngine>()
  private readonly bindings = new Map<string, RuntimeBinding>()
  private readonly starting = new Map<string, Promise<ProtocolEngine>>()
  private handler: (event: EngineEvent) => void = () => undefined
  private started = false

  constructor(
    private readonly store: Store,
    private readonly logger: Logger,
    private readonly factory: RuntimeFactory = (binding) => new ProtocolRuntimeProcess(binding, logger.child({ component: 'runtime-proxy' })),
  ) {}

  setEventHandler(handler: (event: EngineEvent) => void): void { this.handler = handler }

  async start(): Promise<void> {
    const accounts = await this.store.listAccounts()
    for (const account of accounts) {
      this.bindings.set(account.id, {
        definitionId: account.protocolDefinitionId === 'builtin' ? '0' : account.protocolDefinitionId,
        version: account.protocolVersion,
      })
    }
    this.started = true
  }

  async ready(): Promise<void> {
    if (!this.started) throw new Error('versioned protocol engine is not started')
    await Promise.all([...this.runtimes.values()].map((runtime) => runtime.ready()))
  }

  async close(): Promise<void> {
    await Promise.allSettled([...this.runtimes.values()].map((runtime) => runtime.close()))
    this.runtimes.clear()
    this.bindings.clear()
    this.starting.clear()
    this.started = false
  }

  private key(binding: RuntimeBinding): string { return `${binding.definitionId}:${binding.version}` }

  private async runtime(binding: RuntimeBinding): Promise<ProtocolEngine> {
    const key = this.key(binding)
    const existing = this.runtimes.get(key)
    if (existing) return existing
    const pending = this.starting.get(key)
    if (pending) return pending
    const runtime = this.factory(binding)
    runtime.setEventHandler((event) => this.handler(event))
    const start = runtime.start().then(() => {
      this.runtimes.set(key, runtime)
      this.starting.delete(key)
      return runtime
    }).catch((error) => {
      this.starting.delete(key)
      throw error
    })
    this.starting.set(key, start)
    return start
  }

  private bindingFor(accountId: string): RuntimeBinding {
    const binding = this.bindings.get(accountId)
    if (!binding) throw new Error('account protocol binding is unavailable')
    return binding
  }

  private bind(account: EngineAccount): RuntimeBinding {
    const binding = {
      definitionId: account.protocolDefinitionId === 'builtin' ? '0' : account.protocolDefinitionId,
      version: account.protocolVersion,
    }
    this.bindings.set(account.accountId, binding)
    return binding
  }

  async pair(account: EngineAccount): Promise<PairResult> { return (await this.runtime(this.bind(account))).pair(account) }
  async connect(account: EngineAccount): Promise<void> { await (await this.runtime(this.bind(account))).connect(account) }
  async disconnect(accountId: string): Promise<void> { await (await this.runtime(this.bindingFor(accountId))).disconnect(accountId) }
  async logout(account: EngineAccount): Promise<void> { await (await this.runtime(this.bind(account))).logout(account) }
  async send(accountId: string, toE164: string, message: OutboundMessage): Promise<string> {
    return (await this.runtime(this.bindingFor(accountId))).send(accountId, toE164, message)
  }
  async getQuality(accountId: string, policy: SyncPolicy): Promise<AccountQuality> {
    return (await this.runtime(this.bindingFor(accountId))).getQuality(accountId, policy)
  }
  isOnline(accountId: string): boolean {
    const binding = this.bindings.get(accountId)
    return binding ? this.runtimes.get(this.key(binding))?.isOnline(accountId) === true : false
  }
  async protocolVersionInfo(): Promise<ProtocolVersionInfo> {
    const runtime = await this.runtime({ definitionId: '0', version: BUILTIN_BAILEYS_VERSION })
    return runtime.protocolVersionInfo
      ? runtime.protocolVersionInfo()
      : {
          currentWaWebVersion: null,
          latestWaWebVersion: null,
          versionStatus: 'unavailable',
          checkedAt: null,
          checkError: null,
        }
  }
}

export function engineAccount(account: Account): EngineAccount {
  return {
    accountId: account.id,
    protocolDefinitionId: account.protocolDefinitionId,
    protocolVersion: account.protocolVersion,
    phoneE164: account.phoneE164,
    proxyUrl: account.proxyUrl,
    syncPolicy: account.syncPolicy,
  }
}
