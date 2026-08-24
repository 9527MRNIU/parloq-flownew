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

export interface WaWebVersionStatus {
  resolvedVersion: WAVersion
  latestVersion: WAVersion | null
  resolution: 'remote' | 'stale' | 'fallback'
  checkedAt: string
  error: string | null
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
  private cached: { status: WaWebVersionStatus; expiresAt: number } | null = null

  constructor(
    private readonly logger: Logger,
    private readonly fetchVersion: FetchWaWebVersion = fetchLatestWaWebVersion,
  ) {}

  async inspect(
    agent?: Agent,
    requireLatest = false,
  ): Promise<WaWebVersionStatus> {
    const now = Date.now()
    if (this.cached && this.cached.expiresAt > now) return this.cached.status

    const options = {
      timeout: 15_000,
      headers: { 'user-agent': 'Mozilla/5.0' },
      proxy: false as const,
      ...(agent ? { httpAgent: agent, httpsAgent: agent } : {}),
    }
    const result = await this.fetchVersion(options)
    if (result.isLatest) {
      const status: WaWebVersionStatus = {
        resolvedVersion: result.version,
        latestVersion: result.version,
        resolution: 'remote',
        checkedAt: new Date(now).toISOString(),
        error: null,
      }
      this.cached = { status, expiresAt: now + CACHE_TTL_MS }
      this.logger.info(
        { waWebVersion: result.version.join('.') },
        'wa_web_version_resolved',
      )
      return status
    }
    const error = result.error instanceof Error
      ? result.error.message
      : String(result.error ?? 'unknown')
    if (this.cached) {
      return {
        ...this.cached.status,
        latestVersion: null,
        resolution: 'stale',
        checkedAt: new Date(now).toISOString(),
        error,
      }
    }
    if (requireLatest) {
      throw new Error('unable to resolve the current WhatsApp Web client revision')
    }
    this.logger.warn(
      { error },
      'wa_web_version_fallback',
    )
    return {
      resolvedVersion: result.version,
      latestVersion: null,
      resolution: 'fallback',
      checkedAt: new Date(now).toISOString(),
      error,
    }
  }

  async current(agent?: Agent, requireLatest = false): Promise<WAVersion> {
    return (await this.inspect(agent, requireLatest)).resolvedVersion
  }
}
