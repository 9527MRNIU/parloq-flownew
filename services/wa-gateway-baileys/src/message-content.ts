import { isIP } from 'node:net'

import { GatewayError, normalizeE164 } from './domain.js'

export type MessageHeader =
  | { type: 'none' }
  | { type: 'text'; text: string }
  | { type: 'image' | 'video'; media: ManagedMediaReference }
  | { type: 'document'; media: ManagedMediaReference }

export interface ManagedMediaReference {
  id: string
  token: string
  fileName: string
  mimeType: string
  size: number
  sha256: string
}

export type MessageButton =
  | { type: 'quick_reply'; text: string; id: string }
  | { type: 'url'; text: string; url: string }
  | { type: 'call'; text: string; phone: string }
  | { type: 'copy'; text: string; copyText: string }
  | {
      type: 'single_select'
      text: string
      sections: Array<{
        title: string
        rows: Array<{ id: string; title: string; description: string }>
      }>
    }

export interface OutboundMessage {
  version: 1
  header: MessageHeader
  body: { text: string }
  footer: { text: string }
  buttons: MessageButton[]
  fallbackText?: string
}

export interface SendMessageRequest {
  messageId: string
  toE164: string
  text?: string
  message?: unknown
}

const safeId = /^[A-Za-z0-9_.:-]{1,80}$/
const snowflakeId = /^\d{13,19}$/
const sha256 = /^[a-f0-9]{64}$/
const privateIpv4 = /^(?:10\.|127\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new GatewayError('invalid_argument', 'message content has an invalid structure')
  }
  return value as Record<string, unknown>
}

function text(value: unknown, label: string, maximum: number, required = false): string {
  const result = typeof value === 'string' ? value.trim() : ''
  if (required && !result) throw new GatewayError('invalid_argument', `${label} is required`)
  if ([...result].length > maximum) throw new GatewayError('invalid_argument', `${label} is too long`)
  return result
}

function remoteUrl(value: unknown, label: string, httpsOnly = false): string {
  const raw = text(value, label, 2_048, true)
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new GatewayError('invalid_argument', `${label} must be a valid URL`)
  }
  if ((httpsOnly && parsed.protocol !== 'https:') || (!httpsOnly && !['http:', 'https:'].includes(parsed.protocol))) {
    throw new GatewayError('invalid_argument', `${label} has an unsupported protocol`)
  }
  if (parsed.username || parsed.password || !parsed.hostname) {
    throw new GatewayError('invalid_argument', `${label} must not contain credentials`)
  }
  const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '')
  if (hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local')) {
    throw new GatewayError('invalid_argument', `${label} must be publicly reachable`)
  }
  if (isIP(hostname)) {
    if (hostname === '::1' || hostname.startsWith('fc') || hostname.startsWith('fd') || hostname.startsWith('fe80:') || privateIpv4.test(hostname)) {
      throw new GatewayError('invalid_argument', `${label} must be publicly reachable`)
    }
  }
  return parsed.toString()
}

function managedMedia(value: unknown): ManagedMediaReference {
  const raw = object(value)
  const id = text(raw.id, 'material id', 19, true)
  const token = text(raw.token, 'material token', 2_048, true)
  const fileName = text(raw.fileName || 'material', 'file name', 180, true)
  const mimeType = text(raw.mimeType || 'application/octet-stream', 'mime type', 120, true)
  const size = Number(raw.size)
  const digest = text(raw.sha256, 'material sha256', 64, true).toLowerCase()
  if (!snowflakeId.test(id)) throw new GatewayError('invalid_argument', 'material id is invalid')
  if (!Number.isInteger(size) || size < 1 || size > 64 * 1024 * 1024) {
    throw new GatewayError('invalid_argument', 'material size is invalid')
  }
  if (!sha256.test(digest)) throw new GatewayError('invalid_argument', 'material sha256 is invalid')
  return { id, token, fileName, mimeType, size, sha256: digest }
}

function normalizeButton(value: unknown, index: number): MessageButton {
  const raw = object(value)
  const type = text(raw.type, 'button type', 40, true)
  const label = text(raw.text, 'button text', 25, true)
  if (type === 'quick_reply') {
    const id = text(raw.id || `reply_${index + 1}`, 'button id', 80, true)
    if (!safeId.test(id)) throw new GatewayError('invalid_argument', 'button id has unsupported characters')
    return { type, text: label, id }
  }
  if (type === 'url') return { type, text: label, url: remoteUrl(raw.url, 'button URL') }
  if (type === 'call') {
    const phone = String(raw.phone || '').trim()
    return {
      type,
      text: label,
      phone: normalizeE164(phone.startsWith('+') ? phone : `+${phone}`).slice(1),
    }
  }
  if (type === 'copy') return { type, text: label, copyText: text(raw.copyText, 'copy text', 256, true) }
  if (type !== 'single_select') throw new GatewayError('invalid_argument', 'unsupported button type')

  if (!Array.isArray(raw.sections) || !raw.sections.length) {
    throw new GatewayError('invalid_argument', 'single-select button requires sections')
  }
  let rowCount = 0
  const ids = new Set<string>()
  const sections = raw.sections.map((sectionValue, sectionIndex) => {
    const section = object(sectionValue)
    if (!Array.isArray(section.rows) || !section.rows.length) {
      throw new GatewayError('invalid_argument', 'single-select section requires rows')
    }
    const rows = section.rows.map((rowValue, rowIndex) => {
      const row = object(rowValue)
      const id = text(row.id || `option_${rowCount + 1}`, 'row id', 80, true)
      if (!safeId.test(id) || ids.has(id)) throw new GatewayError('invalid_argument', 'row id is invalid or duplicated')
      ids.add(id)
      rowCount += 1
      if (rowCount > 10) throw new GatewayError('invalid_argument', 'single-select supports at most 10 rows')
      return {
        id,
        title: text(row.title || `Option ${rowIndex + 1}`, 'row title', 80, true),
        description: text(row.description, 'row description', 120),
      }
    })
    return {
      title: text(section.title || `Options ${sectionIndex + 1}`, 'section title', 60, true),
      rows,
    }
  })
  return { type, text: label, sections }
}

export function normalizeOutboundMessage(request: Pick<SendMessageRequest, 'text' | 'message'>): OutboundMessage {
  if (request.message === undefined) {
    return {
      version: 1,
      header: { type: 'none' },
      body: { text: text(request.text, 'text', 4_096, true) },
      footer: { text: '' },
      buttons: [],
    }
  }
  const raw = object(request.message)
  const headerRaw = raw.header === undefined ? { type: 'none' } : object(raw.header)
  const headerType = text(headerRaw.type || 'none', 'header type', 20, true)
  let header: MessageHeader
  if (headerType === 'none') header = { type: 'none' }
  else if (headerType === 'text') header = { type: 'text', text: text(headerRaw.text, 'header text', 60, true) }
  else if (headerType === 'image' || headerType === 'video') header = { type: headerType, media: managedMedia(headerRaw.media) }
  else if (headerType === 'document') {
    header = { type: headerType, media: managedMedia(headerRaw.media) }
  } else throw new GatewayError('invalid_argument', 'unsupported header type')

  const body = object(raw.body)
  const footer = raw.footer === undefined ? {} : object(raw.footer)
  if (raw.buttons !== undefined && !Array.isArray(raw.buttons)) {
    throw new GatewayError('invalid_argument', 'buttons must be an array')
  }
  const buttons = (raw.buttons as unknown[] | undefined || []).map(normalizeButton)
  if (buttons.length > 3) throw new GatewayError('invalid_argument', 'at most 3 buttons are supported')
  if (buttons.some((button) => button.type === 'single_select') && buttons.length !== 1) {
    throw new GatewayError('invalid_argument', 'single-select cannot be combined with other buttons')
  }
  return {
    version: 1,
    header,
    body: { text: text(body.text, 'body text', 4_096, true) },
    footer: { text: text(footer.text, 'footer text', 60) },
    buttons,
    ...(raw.fallbackText ? { fallbackText: text(raw.fallbackText, 'fallback text', 4_096) } : {}),
  }
}
