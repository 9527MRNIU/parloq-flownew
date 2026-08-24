import { createHmac } from 'node:crypto'
import type { Logger } from 'pino'
import type { AccountStateWebhookEvent, Message, ProxyHealthWebhookEvent } from './domain.js'
import { safeError } from './domain.js'

export class WebhookClient {
  constructor(
    private readonly url: string,
    private readonly secret: string,
    private readonly retries: number,
    private readonly logger: Logger,
  ) {}

  deliver(message: Message): void {
    if (!this.url) return
    const payload: Record<string, unknown> = {
      event: 'message.status',
      messageId: message.messageId,
      accountId: message.accountId,
      status: message.status,
      timestamp: message.updatedAt,
    }
    if (message.providerMessageId) payload.providerMessageId = message.providerMessageId
    if (message.errorCode) payload.errorCode = message.errorCode
    void this.run(payload, message.messageId).catch((error: unknown) => {
      this.logger.warn({ messageId: message.messageId, status: message.status, error: safeError(error) }, 'status_webhook_failed')
    })
  }

  deliverAccountState(event: AccountStateWebhookEvent): void {
    if (!this.url) return
    const payload: Record<string, unknown> = { ...event }
    void this.run(payload, event.eventId).catch((error: unknown) => {
      this.logger.warn({ eventId: event.eventId, accountId: event.accountId, toState: event.toState, error: safeError(error) }, 'account_state_webhook_failed')
    })
  }

  deliverProxyHealth(event: ProxyHealthWebhookEvent): void {
    if (!this.url) return
    const payload: Record<string, unknown> = { ...event }
    void this.run(payload, event.eventId).catch((error: unknown) => {
      this.logger.warn(
        {
          eventId: event.eventId,
          accountId: event.accountId,
          outcome: event.outcome,
          error: safeError(error),
        },
        'proxy_health_webhook_failed',
      )
    })
  }

  private async run(payload: Record<string, unknown>, deliveryId: string): Promise<void> {
    const body = JSON.stringify(payload)
    const signature = createHmac('sha256', this.secret).update(body).digest('hex')
    let lastError: unknown
    for (let attempt = 0; attempt <= this.retries; attempt += 1) {
      if (attempt) await new Promise((resolve) => setTimeout(resolve, Math.min(4_000, 250 * 2 ** (attempt - 1))))
      try {
        const response = await fetch(this.url, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-parloq-signature': `sha256=${signature}`,
            'x-parloq-event-id': deliveryId,
            'x-parloq-message-id': deliveryId,
          },
          body,
          signal: AbortSignal.timeout(8_000),
        })
        if (response.ok) return
        lastError = new Error(`webhook returned HTTP ${response.status}`)
        // Account creation and the gateway transition are separate database
        // transactions. A brief 404 can mean the control-plane account has not
        // committed yet, so retry it with the same event ID/body.
        if (
          response.status >= 400
          && response.status < 500
          && ![404, 429].includes(response.status)
        ) break
      } catch (error) { lastError = error }
    }
    throw lastError
  }
}
