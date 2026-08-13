import pino from 'pino'
import { loadConfig } from './config.js'
import { BaileysEngine, MockEngine } from './engine.js'
import { buildServer } from './http.js'
import { GatewayService } from './service.js'
import { PostgresStore } from './store.js'
import { WebhookClient } from './webhook.js'

async function main(): Promise<void> {
  const config = loadConfig()
  const logger = pino({ level: process.env.LOG_LEVEL || 'info', redact: ['req.headers.authorization', '*.proxyUrl', '*.session', '*.creds', '*.keys'] })
  const store = new PostgresStore(config.databaseUrl, config.databaseMaxConnections)
  const engine = config.engine === 'baileys' ? new BaileysEngine(store, logger) : new MockEngine()
  const webhook = new WebhookClient(config.webhookUrl, config.webhookSecret, config.webhookRetries, logger)
  const service = new GatewayService(store, engine, webhook, logger, config.queueSize, config.sendQps)
  await service.start()
  const server = buildServer({ service, apiToken: config.apiToken, instanceId: config.instanceId, logger })
  await server.listen({ host: config.address, port: config.port })
  logger.info({ address: `${config.address}:${config.port}`, engine: engine.name }, 'gateway_started')

  const shutdown = async (signal: string) => {
    logger.info({ signal }, 'gateway_shutdown_requested')
    await server.close()
    await service.close()
  }
  process.once('SIGTERM', () => { void shutdown('SIGTERM') })
  process.once('SIGINT', () => { void shutdown('SIGINT') })
}

main().catch((error: unknown) => {
  process.stderr.write(`wa-gateway-baileys failed: ${String(error)}\n`)
  process.exitCode = 1
})
