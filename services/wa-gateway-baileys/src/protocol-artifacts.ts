import { createHash, timingSafeEqual } from 'node:crypto'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { chmod, mkdir, mkdtemp, readFile, realpath, rename, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join, relative, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

export const PROTOCOL_ARTIFACT_SCHEMA_VERSION = 1
export const BUILTIN_BAILEYS_VERSION = '6.7.24'

export interface ProtocolArtifactManifest {
  schemaVersion: typeof PROTOCOL_ARTIFACT_SCHEMA_VERSION
  definitionId: string
  adapterKey: 'baileys'
  packageName: '@whiskeysockets/baileys'
  version: string
  contractVersion: 1
  artifactDigest: string
  artifactIntegrity: string
  entryPath: string
  createdAt: string
}

export interface ProtocolBuildRequest {
  definitionId: string
  adapterKey: string
  packageName: string
  version: string
  contractVersion: number
}

export interface ProtocolBuildOutput {
  manifest: ProtocolArtifactManifest
  logExcerpt: string
}

export class ProtocolArtifactError extends Error {
  constructor(
    readonly code: 'invalid_request' | 'requires_adaptation' | 'build_failed',
    message: string,
    readonly logExcerpt = '',
  ) {
    super(message)
    this.name = 'ProtocolArtifactError'
  }
}

const REQUIRED_BAILEYS_EXPORTS = [
  'default',
  'Browsers',
  'DisconnectReason',
  'BufferJSON',
  'initAuthCreds',
  'proto',
  'fetchLatestWaWebVersion',
  'generateWAMessageFromContent',
  'prepareWAMessageMedia',
  'WAMessageStatus',
] as const

function validateRequest(input: ProtocolBuildRequest): asserts input is ProtocolBuildRequest & {
  adapterKey: 'baileys'
  packageName: '@whiskeysockets/baileys'
  contractVersion: 1
} {
  if (!/^\d{1,20}$/.test(input.definitionId)) {
    throw new ProtocolArtifactError('invalid_request', '协议定义 ID 格式不正确')
  }
  if (input.adapterKey !== 'baileys') {
    throw new ProtocolArtifactError('invalid_request', '该协议适配器未在平台登记')
  }
  if (input.packageName !== '@whiskeysockets/baileys') {
    throw new ProtocolArtifactError('invalid_request', '该软件包未绑定到所选适配器')
  }
  if (input.contractVersion !== 1) {
    throw new ProtocolArtifactError('requires_adaptation', '当前平台尚未适配该契约版本')
  }
  if (!/^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$/.test(input.version)) {
    throw new ProtocolArtifactError('invalid_request', '协议版本格式不正确')
  }
}

function safeArtifactPath(root: string, definitionId: string): string {
  const target = resolve(root, definitionId)
  const normalizedRoot = `${resolve(root)}${sep}`
  if (!`${target}${sep}`.startsWith(normalizedRoot)) {
    throw new ProtocolArtifactError('invalid_request', '协议产物目录不安全')
  }
  return target
}

interface CommandResult { stdout: string; stderr: string }

async function runCommand(
  command: string,
  args: string[],
  options: { cwd: string; timeoutMs: number },
): Promise<CommandResult> {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: {
        PATH: process.env.PATH ?? '',
        HOME: process.env.PROTOCOL_BUILD_HOME ?? tmpdir(),
        npm_config_cache: process.env.PROTOCOL_BUILD_NPM_CACHE ?? join(tmpdir(), 'parloq-protocol-npm-cache'),
      },
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    const append = (current: string, chunk: Buffer, limit: number): string =>
      `${current}${chunk.toString('utf8')}`.slice(-limit)
    // `npm pack --json` includes the package file manifest. Large upstream
    // packages can exceed a short log buffer, and truncating the beginning
    // would make otherwise valid JSON impossible to verify.
    child.stdout.on('data', (chunk: Buffer) => { stdout = append(stdout, chunk, 4 * 1024 * 1024) })
    child.stderr.on('data', (chunk: Buffer) => { stderr = append(stderr, chunk, 32_000) })
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      rejectPromise(new ProtocolArtifactError('build_failed', '协议构建超时', `${stdout}\n${stderr}`.trim()))
    }, options.timeoutMs)
    timer.unref()
    child.once('error', (error) => {
      clearTimeout(timer)
      rejectPromise(new ProtocolArtifactError('build_failed', error.message, `${stdout}\n${stderr}`.trim()))
    })
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      if (code === 0) {
        resolvePromise({ stdout, stderr })
        return
      }
      rejectPromise(new ProtocolArtifactError(
        'build_failed',
        `协议构建命令执行失败（${signal ?? code ?? 'unknown'}）`,
        `${stdout}\n${stderr}`.trim(),
      ))
    })
  })
}

function parsePackResult(stdout: string): { filename: string; integrity: string } {
  try {
    const parsed = JSON.parse(stdout) as Array<{ filename?: unknown; integrity?: unknown }>
    const first = parsed[0]
    if (!first || typeof first.filename !== 'string' || typeof first.integrity !== 'string') throw new Error('missing fields')
    return { filename: basename(first.filename), integrity: first.integrity }
  } catch {
    throw new ProtocolArtifactError('build_failed', 'NPM 未返回软件包完整性信息', stdout)
  }
}

async function sha256Files(paths: string[], metadata: string): Promise<string> {
  const hash = createHash('sha256').update(metadata)
  for (const path of paths) hash.update(await readFile(path))
  return hash.digest('hex')
}

async function smokeTestBaileys(buildDir: string): Promise<string> {
  const requireFromArtifact = createRequire(join(buildDir, 'package.json'))
  let entryPath: string
  try {
    entryPath = requireFromArtifact.resolve('@whiskeysockets/baileys')
  } catch (error) {
    throw new ProtocolArtifactError('build_failed', `无法解析已安装软件包入口：${String(error)}`)
  }
  let loaded: Record<string, unknown>
  try {
    loaded = await import(`${pathToFileURL(entryPath).href}?smoke=${Date.now()}`) as Record<string, unknown>
  } catch (error) {
    throw new ProtocolArtifactError(
      'requires_adaptation',
      `平台适配器无法加载所选版本：${error instanceof Error ? error.message : String(error)}`,
    )
  }
  const missing = REQUIRED_BAILEYS_EXPORTS.filter((name) => !(name in loaded))
  if (missing.length) {
    throw new ProtocolArtifactError(
      'requires_adaptation',
      `所选版本缺少适配器所需接口：${missing.join(', ')}`,
    )
  }
  const canonicalBuildDir = await realpath(buildDir)
  const canonicalEntryPath = await realpath(entryPath)
  const relativeEntryPath = relative(canonicalBuildDir, canonicalEntryPath)
  if (relativeEntryPath.startsWith(`..${sep}`) || relativeEntryPath === '..') {
    throw new ProtocolArtifactError('build_failed', '已安装软件包入口超出构建目录')
  }
  return relativeEntryPath
}

export class ProtocolArtifactBuilder {
  private readonly root: string
  private readonly timeoutMs: number

  constructor(
    root = process.env.PROTOCOL_ARTIFACT_ROOT || '/var/lib/parloq/protocols',
    timeoutSeconds = Number(process.env.PROTOCOL_BUILD_TIMEOUT_SECONDS || 600),
  ) {
    this.root = resolve(root)
    this.timeoutMs = Math.max(60, Math.min(timeoutSeconds, 1800)) * 1_000
  }

  async ready(): Promise<void> {
    await mkdir(this.root, { recursive: true })
    await stat(this.root)
  }

  async build(input: ProtocolBuildRequest): Promise<ProtocolBuildOutput> {
    validateRequest(input)
    await this.ready()
    const buildDir = await mkdtemp(join(this.root, '.build-'))
    const sourceDir = join(buildDir, 'source')
    const logs: string[] = []
    try {
      await mkdir(sourceDir)
      const packed = await runCommand(
        'npm',
        ['pack', `${input.packageName}@${input.version}`, '--json', '--pack-destination', sourceDir],
        { cwd: buildDir, timeoutMs: this.timeoutMs },
      )
      logs.push(packed.stderr.trim())
      const pack = parsePackResult(packed.stdout)
      const tarballPath = join(sourceDir, pack.filename)
      await writeFile(
        join(buildDir, 'package.json'),
        `${JSON.stringify({
          name: `parloq-protocol-${input.definitionId}`,
          private: true,
          type: 'module',
          dependencies: { [input.packageName]: `file:source/${pack.filename}` },
        }, null, 2)}\n`,
        'utf8',
      )
      const installed = await runCommand(
        'npm',
        ['install', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund', '--package-lock=true'],
        { cwd: buildDir, timeoutMs: this.timeoutMs },
      )
      logs.push(installed.stdout.trim(), installed.stderr.trim())
      const entryPath = await smokeTestBaileys(buildDir)
      const lockPath = join(buildDir, 'package-lock.json')
      const artifactDigest = await sha256Files(
        [tarballPath, lockPath],
        `${input.adapterKey}\0${input.version}\0${input.contractVersion}\0`,
      )
      const manifest: ProtocolArtifactManifest = {
        schemaVersion: PROTOCOL_ARTIFACT_SCHEMA_VERSION,
        definitionId: input.definitionId,
        adapterKey: input.adapterKey,
        packageName: input.packageName,
        version: input.version,
        contractVersion: input.contractVersion,
        artifactDigest,
        artifactIntegrity: pack.integrity,
        entryPath,
        createdAt: new Date().toISOString(),
      }
      await writeFile(join(buildDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
      // `mkdtemp` intentionally creates a private 0700 directory. The final
      // artifact is mounted read-only into the gateway and must be traversable
      // by its unprivileged `node` runtime user.
      await chmod(buildDir, 0o755)
      const target = safeArtifactPath(this.root, input.definitionId)
      const previous = `${target}.previous-${Date.now()}`
      try {
        await rename(target, previous)
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
      }
      try {
        await rename(buildDir, target)
      } catch (error) {
        try { await rename(previous, target) } catch { /* best-effort rollback */ }
        throw error
      }
      await rm(previous, { recursive: true, force: true })
      await readProtocolArtifact(input.definitionId, this.root)
      return {
        manifest,
        logExcerpt: logs.filter(Boolean).join('\n').slice(-8_000),
      }
    } catch (error) {
      await rm(buildDir, { recursive: true, force: true })
      if (error instanceof ProtocolArtifactError) throw error
      throw new ProtocolArtifactError(
        'build_failed',
        error instanceof Error ? error.message : String(error),
        logs.filter(Boolean).join('\n').slice(-8_000),
      )
    }
  }
}

export async function readProtocolArtifact(
  definitionId: string,
  root = process.env.PROTOCOL_ARTIFACT_ROOT || '/var/lib/parloq/protocols',
): Promise<{ manifest: ProtocolArtifactManifest; entryUrl: string }> {
  if (!/^\d{1,20}$/.test(definitionId)) throw new Error('invalid protocol definition id')
  const target = safeArtifactPath(root, definitionId)
  const manifest = JSON.parse(await readFile(join(target, 'manifest.json'), 'utf8')) as ProtocolArtifactManifest
  if (
    manifest.schemaVersion !== PROTOCOL_ARTIFACT_SCHEMA_VERSION
    || manifest.definitionId !== definitionId
    || manifest.adapterKey !== 'baileys'
    || manifest.packageName !== '@whiskeysockets/baileys'
    || manifest.contractVersion !== 1
    || !/^[a-f0-9]{64}$/.test(manifest.artifactDigest)
  ) {
    throw new Error('protocol artifact manifest is invalid')
  }
  const entryPath = resolve(target, manifest.entryPath)
  if (!`${entryPath}${sep}`.startsWith(`${target}${sep}`)) throw new Error('protocol artifact entry escaped its root')
  await stat(entryPath)
  return { manifest, entryUrl: pathToFileURL(entryPath).href }
}

export function authorized(header: string | undefined, token: string): boolean {
  if (!token) return true
  const provided = header?.startsWith('Bearer ') ? header.slice(7) : ''
  const expectedBytes = Buffer.from(token)
  const providedBytes = Buffer.from(provided)
  return expectedBytes.length === providedBytes.length && timingSafeEqual(expectedBytes, providedBytes)
}
