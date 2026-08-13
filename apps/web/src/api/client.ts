export type ApiEnvelope<T> = { data: T }
export type ListEnvelope<T> = { data: { rows: T[]; total: number } }

let bearerToken = window.sessionStorage.getItem('parloq-token') || ''

export function setBearerToken(token: string | null) {
  bearerToken = token || ''
  if (bearerToken) window.sessionStorage.setItem('parloq-token', bearerToken)
  else window.sessionStorage.removeItem('parloq-token')
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (bearerToken && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${bearerToken}`)

  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers,
  })

  if (response.status === 401 && path !== '/api/auth/login') {
    setBearerToken(null)
    window.dispatchEvent(new Event('parloq:unauthorized'))
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    const message = payload?.detail || payload?.message || payload?.error || `请求失败（${response.status}）`
    throw new Error(typeof message === 'string' ? message : '请求失败')
  }
  return payload as T
}

export async function apiDownload(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (bearerToken && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${bearerToken}`)

  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers,
  })
  if (response.status === 401) {
    setBearerToken(null)
    window.dispatchEvent(new Event('parloq:unauthorized'))
  }
  if (!response.ok) {
    const contentType = response.headers.get('content-type') || ''
    const payload = contentType.includes('application/json') ? await response.json() : null
    const message = payload?.detail || payload?.message || payload?.error || `请求失败（${response.status}）`
    throw new Error(typeof message === 'string' ? message : '请求失败')
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
