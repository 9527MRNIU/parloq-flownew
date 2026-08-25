import { timingSafeEqual } from 'node:crypto'
import Fastify from 'fastify'
import type { Logger } from 'pino'
import { GatewayError } from './domain.js'
import type { GatewayService } from './service.js'
import type { SendMessageRequest } from './message-content.js'
import { checkProxy } from './proxy-health.js'

interface ServerOptions {
  service: GatewayService
  apiToken: string
  instanceId: string
  logger: Logger
}

function authorized(header: string | undefined, token: string): boolean {
  if (!token) return true
  const provided = header?.startsWith('Bearer ') ? header.slice(7) : ''
  const expectedBytes = Buffer.from(token)
  const providedBytes = Buffer.from(provided)
  return expectedBytes.length === providedBytes.length && timingSafeEqual(expectedBytes, providedBytes)
}

export function buildServer(options: ServerOptions) {
  const app = Fastify({ loggerInstance: options.logger, bodyLimit: 10 * 1024 * 1024 })

  app.get('/healthz', async () => ({ status: 'ok', service: 'wa-gateway', instance_id: options.instanceId, engine: options.service.engineName }))
  app.get('/readyz', async (_request, reply) => {
    try { await options.service.ready(); return { status: 'ready', engine: options.service.engineName } }
    catch { return reply.status(503).send({ status: 'not_ready', engine: options.service.engineName }) }
  })

  app.addHook('preHandler', async (request, reply) => {
    if (!request.url.startsWith('/v1/') && request.url !== '/metrics') return
    if (!authorized(request.headers.authorization, options.apiToken)) {
      return reply.status(401).send({ error: { code: 'unauthorized', message: 'Missing or invalid gateway bearer token.' } })
    }
  })

  app.get('/metrics', async (_request, reply) => reply.type('text/plain; version=0.0.4; charset=utf-8').send(
    '# HELP wa_gateway_info Static gateway identity.\n# TYPE wa_gateway_info gauge\nwa_gateway_info{engine="' + options.service.engineName + '"} 1\n'))

  app.get('/v1/protocol-info', async () => ({ data: await options.service.protocolInfo() }))
  app.post<{ Body: { proxyUrl?: string } }>('/v1/proxy-check', async (request) => ({
    data: await checkProxy(String(request.body?.proxyUrl || '')),
  }))

  app.post<{ Body: { id?: string; protocolDefinitionId?: string; protocolVersion?: string; phoneE164: string; proxyUrl?: string; connectionPolicy?: 'on_demand' | 'always_on'; idleDisconnectSeconds?: number; postVerifyGraceSeconds?: number; syncPolicy?: import('./domain.js').SyncPolicy } }>('/v1/accounts', async (request, reply) => {
    const data = await options.service.createAccount(request.body)
    return reply.status(201).send({ data })
  })
  app.get('/v1/accounts', async () => ({ data: await options.service.listAccounts() }))
  app.get<{ Params: { accountId: string } }>('/v1/accounts/:accountId', async (request) => ({ data: await options.service.getAccount(request.params.accountId) }))
  app.patch<{ Params: { accountId: string }; Body: { phoneE164?: string; proxyUrl?: string; protocolDefinitionId?: string; protocolVersion?: string; autoConnect?: boolean; connectionPolicy?: 'on_demand' | 'always_on'; idleDisconnectSeconds?: number; postVerifyGraceSeconds?: number; syncPolicy?: import('./domain.js').SyncPolicy } }>('/v1/accounts/:accountId', async (request) => ({ data: await options.service.updateAccount(request.params.accountId, request.body) }))
  app.post<{ Params: { accountId: string }; Body: { phoneE164?: string } }>('/v1/accounts/:accountId/pairing-code', async (request) => ({ data: await options.service.requestPairingCode(request.params.accountId, request.body?.phoneE164) }))
  app.post<{ Params: { accountId: string }; Body: { phoneE164?: string } }>('/v1/accounts/:accountId/reauthentication-code', async (request) => ({ data: await options.service.requestReauthenticationCode(request.params.accountId, request.body?.phoneE164) }))
  app.post<{ Params: { accountId: string } }>('/v1/accounts/:accountId/pairing-cancel', async (request) => ({ data: await options.service.cancelPairing(request.params.accountId) }))
  app.post<{ Params: { accountId: string }; Body: { syncPolicy?: import('./domain.js').SyncPolicy } }>('/v1/accounts/:accountId/metadata-sync', async (request) => ({ data: await options.service.syncAccountMetadata(request.params.accountId, request.body ?? {}) }))
  app.post<{ Params: { accountId: string } }>('/v1/accounts/:accountId/connect', async (request) => ({ data: await options.service.connect(request.params.accountId) }))
  app.post<{ Params: { accountId: string } }>('/v1/accounts/:accountId/disconnect', async (request) => ({
    data: await options.service.disconnect(request.params.accountId),
    meta: { sessionPreserved: true, message: 'Disconnected. The saved session can reconnect without pairing again.' },
  }))
  app.post<{ Params: { accountId: string } }>('/v1/accounts/:accountId/logout', async (request) => ({
    data: await options.service.logout(request.params.accountId),
    meta: { sessionPreserved: false, message: 'Logged out. The linked-device session was removed and pairing is required.' },
  }))
  app.post<{ Params: { accountId: string }; Body: { session: unknown; proxyUrl?: string; protocolDefinitionId?: string; protocolVersion?: string } }>('/v1/accounts/:accountId/import-session', async (request) => {
    if (!request.body || !('session' in request.body)) throw new GatewayError('invalid_argument', 'session is required')
    const result = await options.service.importSession(
      request.params.accountId,
      request.body.session,
      request.body.proxyUrl,
      request.body.protocolDefinitionId,
      request.body.protocolVersion,
    )
    return { ...result, data: result }
  })
  app.get<{ Params: { accountId: string } }>('/v1/accounts/:accountId/export-session', async (_request, reply) => {
    reply.header('cache-control', 'no-store')
    const result = await options.service.exportSession(_request.params.accountId)
    return { ...result, data: result }
  })
  app.post<{ Params: { accountId: string }; Body: SendMessageRequest }>('/v1/accounts/:accountId/messages', async (request, reply) => {
    const data = await options.service.sendMessage(request.params.accountId, request.body)
    return reply.status(202).send({ data })
  })
  app.get<{ Params: { messageId: string } }>('/v1/messages/:messageId', async (request) => ({ data: await options.service.getMessage(request.params.messageId) }))

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof GatewayError) {
      const statuses: Record<GatewayError['code'], number> = { not_found: 404, invalid_argument: 400, conflict: 409, account_offline: 409, protocol_error: 502, queue_full: 429 }
      return reply.status(statuses[error.code]).send({
        error: {
          code: error.code,
          message: error.message,
          ...(error.failure ? { failure: error.failure } : {}),
        },
      })
    }
    if ((error as { code?: string }).code === 'FST_ERR_CTP_INVALID_JSON_BODY') {
      return reply.status(400).send({ error: { code: 'invalid_json', message: 'Invalid JSON request.' } })
    }
    request.log.error({ error: error instanceof Error ? error.message : String(error) }, 'gateway_request_failed')
    return reply.status(500).send({ error: { code: 'internal_error', message: 'The gateway could not complete the request.' } })
  })
  return app
}
