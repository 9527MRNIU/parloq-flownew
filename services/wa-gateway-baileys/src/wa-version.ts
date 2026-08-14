import {
  fetchLatestWaWebVersion,
  type WAVersion,
} from '@whiskeysockets/baileys'
import type { Agent } from 'node:https'
import type { Logger } from 'pino'

const CACHE_TTL_MS = 10 * 60_000

export interface WaWebVersionResult {
  version: WAVersion
  isLatest: boolean
  error?: unknown
}

type FetchWaWebVersion = (options: {
  timeout: number
  headers: Record<string, string>
  proxy: false
  httpAgent?: Agent
  httpsAgent?: Agent
}) => Promise<WaWebVersionResult>

/**
 * Baileys stable releases intentionally pin a WA Web revision. WhatsApp can
 * stop accepting that revision before a new Baileys package is published, so
 * fresh companion registration must resolve the revision served by WA itself.
 */
export class WaWebVersionResolver {
  private cached: { version: WAVersion; expiresAt: number } | null = null

  constructor(
    private readonly logger: Logger,
    private readonly fetchVersion: FetchWaWebVersion = fetchLatestWaWebVersion,
  ) {}

  async current(agent?: Agent, requireLatest = false): Promise<WAVersion> {
    const now = Date.now()
    if (this.cached && this.cached.expiresAt > now) return this.cached.version

    const options = {
      timeout: 15_000,
      headers: { 'user-agent': 'Mozilla/5.0' },
      proxy: false as const,
      ...(agent ? { httpAgent: agent, httpsAgent: agent } : {}),
    }
    const result = await this.fetchVersion(options)
    if (result.isLatest) {
      this.cached = { version: result.version, expiresAt: now + CACHE_TTL_MS }
      this.logger.info(
        { waWebVersion: result.version.join('.') },
        'wa_web_version_resolved',
      )
      return result.version
    }
    if (this.cached) return this.cached.version
    if (requireLatest) {
      throw new Error('unable to resolve the current WhatsApp Web client revision')
    }
    this.logger.warn(
      { error: result.error instanceof Error ? result.error.message : String(result.error ?? 'unknown') },
      'wa_web_version_fallback',
    )
    return result.version
  }
}
