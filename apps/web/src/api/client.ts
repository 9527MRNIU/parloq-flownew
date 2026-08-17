export type ApiEnvelope<T> = { data: T }
export type ListEnvelope<T> = { data: { rows: T[]; total: number } }

// Browser authentication is cookie-only. Remove tokens left by older builds so
// script-readable credentials do not survive an upgrade in sessionStorage.
window.sessionStorage.removeItem('parloq-token')

function apiErrorMessage(payload: unknown, status: number): string {
  if (!payload || typeof payload !== 'object') return `请求失败（${status}）`
  const body = payload as Record<string, unknown>
  for (const key of ['detail', 'message', 'error']) {
    const value = body[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  if (Array.isArray(body.detail)) {
    const messages = body.detail
      .map((item) => {
        if (!item || typeof item !== 'object') return ''
        const error = item as Record<string, unknown>
        const location = Array.isArray(error.loc)
          ? error.loc.filter((part) => part !== 'body').join('.')
          : ''
        const message = typeof error.msg === 'string' ? error.msg : ''
        return [location, message].filter(Boolean).join('：')
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  return `请求失败（${status}）`
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  // Let the browser attach the multipart boundary for FormData and preserve
  // native content types for Blob/URLSearchParams. JSON bodies in this client
  // are serialized strings, so only those receive the JSON content type.
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers,
  })

  if (response.status === 401 && path !== '/api/auth/login') {
    window.dispatchEvent(new Event('parloq:unauthorized'))
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    throw new Error(apiErrorMessage(payload, response.status))
  }
  return payload as T
}

export async function apiDownload(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers,
  })
  if (response.status === 401) {
    window.dispatchEvent(new Event('parloq:unauthorized'))
  }
  if (!response.ok) {
    const contentType = response.headers.get('content-type') || ''
    const payload = contentType.includes('application/json') ? await response.json() : null
    throw new Error(apiErrorMessage(payload, response.status))
  }
  return {
    blob: await response.blob(),
    filename: response.headers
      .get('content-disposition')
      ?.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i)?.[1],
  }
}

export function unwrapList<T>(payload: unknown): { rows: T[]; total: number } {
  const value = payload as { data?: unknown; rows?: T[]; total?: number }
  const body = value?.data ?? value
  if (Array.isArray(body)) return { rows: body as T[], total: body.length }
  const list = body as { rows?: T[]; items?: T[]; total?: number }
  const rows = list?.rows ?? list?.items ?? []
  return { rows, total: Number(list?.total ?? rows.length) }
}

export function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

export function formatLocalDateInput(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
