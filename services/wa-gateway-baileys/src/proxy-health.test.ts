import { describe, expect, it } from 'vitest'
import {
  classifyProxyFailure,
  parseProxyCountryTrace,
  proxyFingerprint,
} from './proxy-health.js'

describe('proxy health classification', () => {
  it('distinguishes authentication failures from transient connection failures', () => {
    expect(classifyProxyFailure(new Error('Proxy Authentication Required (407)')))
      .toBe('proxy_authentication_failed')
    expect(classifyProxyFailure(new Error('connect ECONNREFUSED 203.0.113.10:8080')))
      .toBe('proxy_connection_failed')
    expect(classifyProxyFailure(new Error('WhatsApp logged out the linked device')))
      .toBeNull()
  })

  it('uses a stable fingerprint without exposing credentials', () => {
    const url = 'http://user:secret@203.0.113.10:8080'
    const fingerprint = proxyFingerprint(url)
    expect(fingerprint).toMatch(/^[a-f0-9]{64}$/)
    expect(fingerprint).not.toContain('secret')
    expect(proxyFingerprint(url)).toBe(fingerprint)
  })

  it('parses the proxy egress country from a Cloudflare trace response', () => {
    expect(parseProxyCountryTrace('ip=203.0.113.10\nloc=br\ncolo=GRU\n')).toBe('BR')
    expect(parseProxyCountryTrace('ip=203.0.113.10\nloc=XX\n')).toBeNull()
    expect(parseProxyCountryTrace('ip=203.0.113.10\ncolo=GRU\n')).toBeNull()
  })
})
