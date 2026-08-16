import { describe, expect, it } from 'vitest'

import { nativeFlowButton } from './engine.js'
import { normalizeOutboundMessage } from './message-content.js'

describe('structured outbound messages', () => {
  it('keeps the legacy text contract working', () => {
    expect(normalizeOutboundMessage({ text: ' hello ' })).toEqual({
      version: 1,
      header: { type: 'none' },
      body: { text: 'hello' },
      footer: { text: '' },
      buttons: [],
    })
  })

  it('normalizes media, footer and supported buttons', () => {
    const media = {
      id: '4780486454931715',
      token: 'signed-material-token',
      fileName: 'banner.png',
      mimeType: 'image/png',
      size: 67,
      sha256: 'a'.repeat(64),
    }
    const message = normalizeOutboundMessage({
      message: {
        header: { type: 'image', media },
        body: { text: 'Offer for {{name}}' },
        footer: { text: 'Terms apply' },
        buttons: [
          { type: 'url', text: 'View offer', url: 'https://example.test/offer' },
          { type: 'call', text: 'Call', phone: '8613800000000' },
          { type: 'copy', text: 'Copy code', copyText: 'SAVE20' },
        ],
      },
    })
    expect(message.header).toEqual({ type: 'image', media })
    expect(message.buttons[1]).toEqual({ type: 'call', text: 'Call', phone: '8613800000000' })
    expect(nativeFlowButton(message.buttons[0]!)).toEqual({
      name: 'cta_url',
      buttonParamsJson: JSON.stringify({
        display_text: 'View offer',
        url: 'https://example.test/offer',
        merchant_url: 'https://example.test/offer',
      }),
    })
  })

  it('rejects external media URLs and mixed single-select buttons', () => {
    expect(() => normalizeOutboundMessage({
      message: {
        header: { type: 'image', url: 'https://cdn.example.test/banner.jpg' },
        body: { text: 'hello' },
      },
    })).toThrow(/invalid structure/)
    expect(() => normalizeOutboundMessage({
      message: {
        header: { type: 'none' },
        body: { text: 'hello' },
        buttons: [
          {
            type: 'single_select',
            text: 'Choose',
            sections: [{ title: 'Options', rows: [{ id: 'a', title: 'A' }] }],
          },
          { type: 'quick_reply', text: 'Reply', id: 'reply' },
        ],
      },
    })).toThrow(/cannot be combined/)
  })
})
