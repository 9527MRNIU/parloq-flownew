import { createHash } from 'node:crypto'
import https from 'node:https'
import { ProxyAgent } from 'proxy-agent'
import { safeError, validateProxy } from './domain.js'

export const proxyHealthTarget = 'https://web.whatsapp.com/sw.js'
export const proxyCountryTarget = 'https://cloudflare.com/cdn-cgi/trace'

export interface ProxyCheckResult {
  healthy: boolean
  latencyMs: number | null
  reasonCategory: string
  error?: string
  countryCode?: string
}

export function proxyFingerprint(proxyUrl: string): string {
  return createHash('sha256').update(proxyUrl).digest('hex')
}

export function classifyProxyFailure(error: unknown): string | null {
  const message = safeError(error).toLowerCase()
  if (/\b407\b|proxy authentication|proxy auth|authentication required/.test(message)) {
    return 'proxy_authentication_failed'
  }
  if (/invalid proxy|unsupported proxy|invalid url|proxyurl/.test(message)) {
    return 'proxy_configuration_invalid'
  }
  if (
    /econnrefused|econnreset|enotfound|ehostunreach|enetunreach|etimedout|connect timeout|socket hang up|proxy connection|tunneling socket|timed out waiting/.test(message)
  ) {
    return 'proxy_connection_failed'
  }
  return null
}

function publicError(reason: string): string {
  if (reason === 'proxy_authentication_failed') return '代理认证失败，请检查账号和密码'
  if (reason === 'proxy_configuration_invalid') return '代理配置无效'
  if (reason === 'proxy_target_rejected') return '代理未能正常访问 WhatsApp Web'
  return '代理连接 WhatsApp Web 失败'
}

export function parseProxyCountryTrace(trace: string): string | null {
  const location = trace
    .split(/\r?\n/)
    .find((line) => line.startsWith('loc='))
    ?.slice(4)
    .trim()
    .toUpperCase()
  return location && /^[A-Z]{2}$/.test(location) && location !== 'XX'
    ? location
    : null
}

function detectProxyCountry(proxyAgent: ProxyAgent): Promise<string | null> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (countryCode: string | null) => {
      if (settled) return
      settled = true
      resolve(countryCode)
    }
    const request = https.get(
      proxyCountryTarget,
      {
        agent: proxyAgent,
        headers: {
          accept: 'text/plain',
          'user-agent': 'Parloq-Proxy-Country/1.0',
        },
      },
      (response) => {
        if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 400) {
          response.resume()
          finish(null)
          return
        }
        let trace = ''
        response.on('data', (chunk: Buffer) => {
          if (trace.length >= 8192) return
          trace += chunk.toString('utf8', 0, Math.max(0, 8192 - trace.length))
        })
        response.on('end', () => finish(parseProxyCountryTrace(trace)))
      },
    )
    request.setTimeout(6_000, () => {
      request.destroy(new Error('proxy country detection timed out'))
    })
    request.on('error', () => finish(null))
  })
}

function checkWhatsAppReachability(
  proxyAgent: ProxyAgent,
  startedAt: number,
): Promise<ProxyCheckResult> {
  return new Promise<ProxyCheckResult>((resolve) => {
    let settled = false
    const finish = (result: ProxyCheckResult) => {
      if (settled) return
      settled = true
      resolve(result)
    }
    const request = https.get(
      proxyHealthTarget,
      {
        agent: proxyAgent,
        headers: {
          accept: 'application/javascript,*/*;q=0.8',
          'user-agent': 'Parloq-Proxy-Health/1.0',
        },
      },
      (response) => {
        const statusCode = response.statusCode ?? 0
        let received = 0
        response.on('data', (chunk: Buffer) => {
          received += chunk.length
          if (statusCode >= 200 && statusCode < 400 && received > 0) {
            finish({
              healthy: true,
              latencyMs: Date.now() - startedAt,
              reasonCategory: 'proxy_ok',
            })
            response.destroy()
          }
        })
        response.on('end', () => {
          const healthy = statusCode >= 200 && statusCode < 400 && received > 0
          finish({
            healthy,
            latencyMs: Date.now() - startedAt,
            reasonCategory: healthy ? 'proxy_ok' : 'proxy_target_rejected',
            ...(healthy ? {} : { error: publicError('proxy_target_rejected') }),
          })
        })
      },
    )
    request.setTimeout(12_000, () => {
      request.destroy(new Error('proxy connection timed out'))
    })
    request.on('error', (error) => {
      if (settled) return
      const reason = classifyProxyFailure(error) ?? 'proxy_connection_failed'
      finish({
        healthy: false,
        latencyMs: null,
        reasonCategory: reason,
        error: publicError(reason),
      })
    })
  })
}

export async function checkProxy(rawProxyUrl: string): Promise<ProxyCheckResult> {
  const proxyUrl = validateProxy(rawProxyUrl)
  if (!proxyUrl) {
    return {
      healthy: false,
      latencyMs: null,
      reasonCategory: 'proxy_configuration_invalid',
      error: publicError('proxy_configuration_invalid'),
    }
  }
  const startedAt = Date.now()
  const proxyAgent = new ProxyAgent({ getProxyForUrl: () => proxyUrl })
  try {
    const [health, countryCode] = await Promise.all([
      checkWhatsAppReachability(proxyAgent, startedAt),
      detectProxyCountry(proxyAgent),
    ])
    return countryCode ? { ...health, countryCode } : health
  } finally {
    proxyAgent.destroy()
  }
}
