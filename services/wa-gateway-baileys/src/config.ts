export interface Config {
  address: string
  port: number
  instanceId: string
  engine: 'mock' | 'baileys'
  databaseUrl: string
  databaseMaxConnections: number
  apiToken: string
  webhookUrl: string
  webhookSecret: string
  webhookRetries: number
  queueSize: number
  sendQps: number
  materialBaseUrl: string
}

function intEnv(name: string, fallback: number, min: number, max: number): number {
  const raw = process.env[name]
  const value = raw ? Number(raw) : fallback
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name} must be an integer between ${min} and ${max}`)
  return value
}

export function loadConfig(): Config {
  const databaseUrl = (process.env.WA_GATEWAY_DATABASE_URL || process.env.DATABASE_URL || '').trim()
  if (!databaseUrl) throw new Error('WA_GATEWAY_DATABASE_URL or DATABASE_URL is required')
  const engine = (process.env.WA_ENGINE || 'mock').trim()
  if (engine !== 'mock' && engine !== 'baileys') throw new Error(`unsupported WA_ENGINE ${engine}`)
  const apiToken = (process.env.WA_GATEWAY_API_TOKEN || '').trim()
  if (engine === 'baileys' && apiToken.length < 32) throw new Error('WA_GATEWAY_API_TOKEN must contain at least 32 characters with WA_ENGINE=baileys')
  const webhookUrl = (process.env.WA_GATEWAY_WEBHOOK_URL || '').trim()
  const webhookSecret = (process.env.WA_GATEWAY_WEBHOOK_SECRET || '').trim()
  if (webhookUrl && webhookSecret.length < 16) throw new Error('WA_GATEWAY_WEBHOOK_SECRET must contain at least 16 characters when webhook is enabled')
  const rawAddress = process.env.WA_GATEWAY_ADDR || ':8010'
  const match = rawAddress.match(/^(.*):(\d+)$/)
  if (!match) throw new Error('WA_GATEWAY_ADDR must use host:port format')
  return {
    address: match[1] || '0.0.0.0',
    port: Number(match[2]),
    instanceId: process.env.WA_GATEWAY_INSTANCE_ID || 'local-wa-gateway-baileys-1',
    engine,
    databaseUrl,
    databaseMaxConnections: intEnv('WA_GATEWAY_DATABASE_MAX_CONNECTIONS', 50, 2, 500),
    apiToken,
    webhookUrl,
    webhookSecret,
    webhookRetries: intEnv('WA_GATEWAY_WEBHOOK_RETRIES', 3, 0, 10),
    queueSize: intEnv('WA_GATEWAY_ACCOUNT_QUEUE_SIZE', 1_000, 10, 100_000),
    sendQps: intEnv('WA_GATEWAY_SEND_QPS', 10, 1, 10),
    materialBaseUrl: (process.env.WA_GATEWAY_MATERIAL_BASE_URL || 'http://api:8000').replace(/\/$/, ''),
  }
}
