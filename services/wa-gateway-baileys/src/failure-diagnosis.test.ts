import { describe, expect, it } from 'vitest'
import { GatewayError } from './domain.js'
import { diagnosePairingFailure } from './failure-diagnosis.js'

describe('pairing failure diagnosis', () => {
  it('preserves a proxy authentication root cause behind version resolution', () => {
    const error = new Error(
      'unable to resolve the current WhatsApp Web client revision',
      { cause: new Error('Socks5 Authentication failed') },
    )

    expect(diagnosePairingFailure(error, { stage: 'pairing_start' })).toEqual({
      code: 'proxy_authentication_failed',
      title: '代理认证失败',
      message: '账号连接线路拒绝了当前认证信息。',
      suggestion: '请检查或更换绑定代理后重新获取配对码。',
      stage: 'connection_route',
      retryable: true,
      technicalMessage: 'Socks5 Authentication failed',
    })
  })

  it('maps exhausted pair-device refs to a confirmation timeout', () => {
    expect(diagnosePairingFailure(
      new Error('QR refs attempts ended'),
      { stage: 'wait_pair_success', protocolCode: '408' },
    )).toMatchObject({
      code: 'pairing_confirmation_timeout',
      title: '配对确认超时',
      stage: 'wait_pair_success',
      protocolCode: '408',
      technicalMessage: 'QR refs attempts ended',
      retryable: true,
    })
  })

  it('redacts credentials from technical messages', () => {
    const diagnosed = diagnosePairingFailure(
      new Error('connect socks5://user:secret@proxy.example:1080 failed'),
      { stage: 'connection' },
    )
    expect(diagnosed.technicalMessage).toContain('socks5://[REDACTED]@')
    expect(diagnosed.technicalMessage).not.toContain('user:secret')
  })

  it('preserves a diagnosis returned by a versioned protocol runtime', () => {
    const failure = {
      code: 'proxy_authentication_failed',
      title: '代理认证失败',
      message: '账号连接线路拒绝了当前认证信息。',
      suggestion: '请检查或更换绑定代理后重新获取配对码。',
      stage: 'connection_route',
      retryable: true,
      technicalMessage: 'Socks5 Authentication failed',
    }
    const error = new GatewayError('protocol_error', 'runtime request failed', failure)

    expect(diagnosePairingFailure(error, { stage: 'pairing_start' })).toBe(failure)
  })
})
