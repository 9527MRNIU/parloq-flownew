package metrics

import (
	"fmt"
	"io"
	"sync/atomic"
)

type Registry struct {
	AccountsCreated atomic.Uint64
	PairingRequests atomic.Uint64
	Connects        atomic.Uint64
	Disconnects     atomic.Uint64
	MessagesQueued  atomic.Uint64
	MessagesSent    atomic.Uint64
	MessagesFailed  atomic.Uint64
	Delivered       atomic.Uint64
	WebhookFailed   atomic.Uint64
	ActiveAccounts  atomic.Int64
}

func (r *Registry) WritePrometheus(writer io.Writer) {
	writeCounter(writer, "wa_gateway_accounts_created_total", r.AccountsCreated.Load())
	writeCounter(writer, "wa_gateway_pairing_requests_total", r.PairingRequests.Load())
	writeCounter(writer, "wa_gateway_connects_total", r.Connects.Load())
	writeCounter(writer, "wa_gateway_disconnects_total", r.Disconnects.Load())
	writeCounter(writer, "wa_gateway_messages_queued_total", r.MessagesQueued.Load())
	writeCounter(writer, "wa_gateway_messages_sent_total", r.MessagesSent.Load())
	writeCounter(writer, "wa_gateway_messages_failed_total", r.MessagesFailed.Load())
	writeCounter(writer, "wa_gateway_messages_delivered_total", r.Delivered.Load())
	writeCounter(writer, "wa_gateway_webhook_failures_total", r.WebhookFailed.Load())
	_, _ = fmt.Fprintf(writer, "# TYPE wa_gateway_active_accounts gauge\nwa_gateway_active_accounts %d\n", r.ActiveAccounts.Load())
}

func writeCounter(writer io.Writer, name string, value uint64) {
	_, _ = fmt.Fprintf(writer, "# TYPE %s counter\n%s %d\n", name, name, value)
}
