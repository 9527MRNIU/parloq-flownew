import * as BuiltinBaileys from '@whiskeysockets/baileys'
import pino from 'pino'
import type { BaileysRuntimeModule } from './auth-store.js'
import type { EngineAccount, ProtocolVersionInfo } from './engine.js'
import { BaileysEngine } from './engine.js'
import { diagnosePairingFailure } from './failure-diagnosis.js'
import type { OutboundMessage } from './message-content.js'
import { BUILTIN_BAILEYS_VERSION, readProtocolArtifact } from './protocol-artifacts.js'
import { PostgresStore } from './store.js'

type RuntimeMethod =
  | 'ready'
  | 'close'
  | 'pair'
  | 'connect'
  | 'disconnect'
  | 'logout'
  | 'send'
  | 'getQuality'
  | 'protocolVersionInfo'

interface RuntimeCommand {
  kind: 'command'
  id: number
  method: RuntimeMethod
  args: unknown[]
}

function send(value: unknown, callback?: () => void): void {
  if (process.send && callback) process.send(value, () => callback())
  else if (process.send) process.send(value)
  else callback?.()
}

async function loadRuntimeModule(
  definitionId: string,
  version: string,
): Promise<BaileysRuntimeModule> {
  try {
    const artifact = await readProtocolArtifact(definitionId)
    if (artifact.manifest.version !== version) throw new Error('protocol artifact version does not match the requested runtime')
    return await import(`${artifact.entryUrl}?runtime=${encodeURIComponent(definitionId)}`) as BaileysRuntimeModule
  } catch (error) {
    if (version === BUILTIN_BAILEYS_VERSION) return BuiltinBaileys
    throw error
  }
}

async function main(): Promise<void> {
  const definitionId = String(process.env.PROTOCOL_DEFINITION_ID || '')
  const version = String(process.env.PROTOCOL_VERSION || '')
  if (!/^\d{1,20}$/.test(definitionId) || !version) throw new Error('runtime protocol binding is invalid')
  const databaseUrl = String(process.env.WA_GATEWAY_DATABASE_URL || process.env.DATABASE_URL || '')
  if (!databaseUrl) throw new Error('runtime database URL is required')
  const logger = pino({
    level: process.env.LOG_LEVEL || 'info',
    redact: ['*.proxyUrl', '*.session', '*.creds', '*.keys', '*.token'],
  }).child({ definitionId, version, component: 'protocol-runtime' })
  const store = new PostgresStore(
    databaseUrl,
    Number(process.env.WA_PROTOCOL_RUNTIME_DATABASE_MAX_CONNECTIONS || 10),
  )
  const baileys = await loadRuntimeModule(definitionId, version)
  const engine = new BaileysEngine(
    store,
    logger,
    process.env.WA_GATEWAY_MATERIAL_BASE_URL || 'http://api:8000',
    baileys,
  )
  engine.setEventHandler((event) => send({ kind: 'event', event }))
  await engine.start()
  send({ kind: 'ready', definitionId, version })

  process.on('message', (raw: unknown) => {
    const command = raw as RuntimeCommand
    if (!command || command.kind !== 'command' || !Number.isInteger(command.id)) return
    void (async () => {
      let result: unknown
      switch (command.method) {
        case 'ready':
          result = await engine.ready()
          break
        case 'close':
          await engine.close()
          await store.close()
          result = null
          break
        case 'pair':
          result = await engine.pair(command.args[0] as EngineAccount)
          break
        case 'connect':
          result = await engine.connect(command.args[0] as EngineAccount)
          break
        case 'disconnect':
          result = await engine.disconnect(String(command.args[0]))
          break
        case 'logout':
          result = await engine.logout(command.args[0] as EngineAccount)
          break
        case 'send':
          result = await engine.send(
            String(command.args[0]),
            String(command.args[1]),
            command.args[2] as OutboundMessage,
          )
          break
        case 'getQuality':
          result = await engine.getQuality(
            String(command.args[0]),
            command.args[1] as EngineAccount['syncPolicy'],
          )
          break
        case 'protocolVersionInfo':
          result = engine.protocolVersionInfo
            ? await engine.protocolVersionInfo()
            : null satisfies ProtocolVersionInfo | null
          break
      }
      if (command.method === 'close') {
        send({ kind: 'response', id: command.id, ok: true, result }, () => process.exit(0))
      } else {
        send({ kind: 'response', id: command.id, ok: true, result })
      }
    })().catch((error: unknown) => {
      const failure = command.method === 'pair'
        ? diagnosePairingFailure(error, { stage: 'pairing_start' })
        : undefined
      send({
        kind: 'response',
        id: command.id,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        ...(failure ? { failure } : {}),
      })
    })
  })

  const shutdown = async () => {
    await engine.close()
    await store.close()
    process.exit(0)
  }
  process.once('SIGTERM', () => { void shutdown() })
  process.once('SIGINT', () => { void shutdown() })
}

main().catch((error: unknown) => {
  send({ kind: 'startup-error', error: error instanceof Error ? error.message : String(error) })
  process.stderr.write(`protocol-runtime failed: ${String(error)}\n`)
  process.exitCode = 1
})
