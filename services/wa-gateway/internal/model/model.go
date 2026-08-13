package model

import "time"

type Account struct {
	ID          string    `json:"id"`
	PhoneE164   string    `json:"phoneE164"`
	ProxyURL    string    `json:"-"`
	ProxyMasked string    `json:"proxy"`
	State       string    `json:"state"`
	DeviceJID   string    `json:"deviceJid,omitempty"`
	AutoConnect bool      `json:"autoConnect"`
	LeaseEpoch  int64     `json:"-"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`
}

type MessageStatus string

const (
	MessageQueued    MessageStatus = "queued"
	MessageSent      MessageStatus = "sent"
	MessageDelivered MessageStatus = "delivered"
	MessageFailed    MessageStatus = "failed"
)

type Message struct {
	ID                string        `json:"messageId"`
	AccountID         string        `json:"accountId"`
	RecipientE164     string        `json:"recipientE164"`
	ProviderMessageID string        `json:"providerMessageId,omitempty"`
	Status            MessageStatus `json:"status"`
	ErrorCode         string        `json:"errorCode,omitempty"`
	QueuedAt          time.Time     `json:"queuedAt"`
	SentAt            *time.Time    `json:"sentAt,omitempty"`
	DeliveredAt       *time.Time    `json:"deliveredAt,omitempty"`
	UpdatedAt         time.Time     `json:"updatedAt"`
}
