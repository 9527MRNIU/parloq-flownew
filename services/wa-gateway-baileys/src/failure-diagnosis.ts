import type { FailureDiagnosis } from './domain.js'
import { GatewayError, safeError } from './domain.js'

interface DiagnosisOptions {
  stage: string
  protocolCode?: string
}

function errorMessages(error: unknown): string[] {
  const messages: string[] = []
  const seen = new Set<unknown>()
  let current: unknown = error
  while (current !== undefined && current !== null && !seen.has(current)) {
    seen.add(current)
    const message = safeError(current).trim()
    if (message && !messages.includes(message)) messages.push(message)
    current = current instanceof Error ? current.cause : undefined
  }
  return messages
}

function withTechnicalMessage(
  diagnosis: Omit<FailureDiagnosis, 'technicalMessage' | 'protocolCode'>,
  messages: string[],
  protocolCode?: string,
): FailureDiagnosis {
  const technicalMessage = messages.at(-1)?.slice(0, 500)
  return {
    ...diagnosis,
    ...(protocolCode ? { protocolCode } : {}),
    ...(technicalMessage ? { technicalMessage } : {}),
  }
}

export function diagnosePairingFailure(
  error: unknown,
  options: DiagnosisOptions,
): FailureDiagnosis {
  if (error instanceof GatewayError && error.failure) return error.failure
  const messages = errorMessages(error)
  const searchable = messages.join(' | ').toLowerCase()

  if (/socks5? authentication failed|proxy authentication|required authentication/.test(searchable)) {
    return withTechnicalMessage({
      code: 'proxy_authentication_failed',
      title: '代理认证失败',
      message: '账号连接线路拒绝了当前认证信息。',
      suggestion: '请检查或更换绑定代理后重新获取配对码。',
      stage: 'connection_route',
      retryable: true,
    }, messages, options.protocolCode)
  }
  if (searchable.includes('qr refs attempts ended')) {
    return withTechnicalMessage({
      code: 'pairing_confirmation_timeout',
      title: '配对确认超时',
      message: '手机未在配对会话有效期内完成绑定。',
      suggestion: '请重新获取配对码，并及时在手机端完成确认。',
      stage: 'wait_pair_success',
      retryable: true,
    }, messages, options.protocolCode)
  }
  if (searchable.includes('timed out waiting for whatsapp pairing registration')) {
    return withTechnicalMessage({
      code: 'pairing_registration_timeout',
      title: '配对通道准备超时',
      message: 'WhatsApp 配对通道未能及时完成初始化。',
      suggestion: '请检查连接线路后重新获取配对码。',
      stage: 'prepare_pairing',
      retryable: true,
    }, messages, options.protocolCode)
  }
  if (searchable.includes('unable to resolve the current whatsapp web client revision')) {
    return withTechnicalMessage({
      code: 'whatsapp_version_unavailable',
      title: 'WhatsApp 版本信息获取失败',
      message: '网关未能获取当前 WhatsApp Web 版本。',
      suggestion: '请检查连接线路后重试；若持续失败，请检查协议版本。',
      stage: 'resolve_wa_version',
      retryable: true,
    }, messages, options.protocolCode)
  }
  if (options.protocolCode === '408' || /timed out|timeout/.test(searchable)) {
    return withTechnicalMessage({
      code: 'pairing_connection_timeout',
      title: '配对连接超时',
      message: '配对连接未在有效时间内完成。',
      suggestion: '请重新获取配对码并再次尝试。',
      stage: options.stage,
      retryable: true,
    }, messages, options.protocolCode)
  }
  return withTechnicalMessage({
    code: 'pairing_gateway_failed',
    title: '账号服务连接失败',
    message: '网关未能完成本次配对请求。',
    suggestion: '请检查协议节点和连接线路后重试。',
    stage: options.stage,
    retryable: true,
  }, messages, options.protocolCode)
}
