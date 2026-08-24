import Fastify from 'fastify'
import pino from 'pino'
import { authorized, ProtocolArtifactBuilder, ProtocolArtifactError, type ProtocolBuildRequest } from './protocol-artifacts.js'


async function main(): Promise<void> {
  const logger = pino({ level: process.env.LOG_LEVEL || 'info' })
  const builder = new ProtocolArtifactBuilder()
  await builder.ready()
  const app = Fastify({ loggerInstance: logger, bodyLimit: 64 * 1024 })
  const token = (process.env.PROTOCOL_BUILDER_API_TOKEN || process.env.WA_GATEWAY_API_TOKEN || '').trim()
  const port = Number(process.env.PROTOCOL_BUILDER_PORT || 8011)

  app.get('/healthz', async () => ({ status: 'ok', service: 'protocol-builder' }))
  app.get('/readyz', async (_request, reply) => {
    try {
      await builder.ready()
      return { status: 'ready' }
    } catch {
      return reply.status(503).send({ status: 'not_ready' })
    }
  })
  app.addHook('preHandler', async (request, reply) => {
    if (!request.url.startsWith('/v1/')) return
    if (!authorized(request.headers.authorization, token)) {
      return reply.status(401).send({ error: { code: 'unauthorized', message: 'Missing or invalid builder bearer token.' } })
    }
  })
  app.post<{ Body: ProtocolBuildRequest }>('/v1/protocol-builds', async (request, reply) => {
    try {
      const output = await builder.build(request.body)
      return {
        data: {
          artifactDigest: output.manifest.artifactDigest,
          artifactIntegrity: output.manifest.artifactIntegrity,
          logExcerpt: output.logExcerpt,
        },
      }
    } catch (error) {
      if (error instanceof ProtocolArtifactError) {
        const status = error.code === 'invalid_request' ? 422 : error.code === 'requires_adaptation' ? 409 : 500
        return reply.status(status).send({
          error: {
            code: error.code,
            message: error.message,
            logExcerpt: error.logExcerpt,
          },
        })
      }
      request.log.error({ error: error instanceof Error ? error.message : String(error) }, 'protocol_build_failed')
      return reply.status(500).send({ error: { code: 'build_failed', message: 'Protocol build failed.' } })
    }
  })
  await app.listen({ host: '0.0.0.0', port })
  logger.info({ port }, 'protocol_builder_started')

  const shutdown = async () => { await app.close() }
  process.once('SIGTERM', () => { void shutdown() })
  process.once('SIGINT', () => { void shutdown() })
}

main().catch((error: unknown) => {
  process.stderr.write(`protocol-builder failed: ${String(error)}\n`)
  process.exitCode = 1
})
