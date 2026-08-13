// Package engine defines the protocol boundary between the Parloq data plane
// and a concrete WhatsApp Web implementation.
package engine

import (
	"context"
	"errors"
	"time"
)

var (
	ErrAccountNotFound = errors.New("engine account not found")
	ErrAccountOffline  = errors.New("engine account is offline")
)

type PairMethod string

const (
	PairMethodCode PairMethod = "pairing_code"
	PairMethodQR   PairMethod = "qr_code"
)

type PairRequest struct {
	AccountID string
	Method    PairMethod
	PhoneE164 string
	ProxyURL  string
}

type PairResult struct {
	AccountID string    `json:"accountId"`
	Code      string    `json:"code"`
	ExpiresAt time.Time `json:"expiresAt"`
	DeviceJID string    `json:"deviceJid,omitempty"`
}

type AccountConfig struct {
	AccountID string
	ProxyURL  string
	DeviceJID string
}

type Message struct {
	RequestID string
	AccountID string
	ToE164    string
	Text      string
}

type SendResult struct {
	ProviderMessageID string
	ServerAcceptedAt  time.Time
}

type AccountStatus struct {
	AccountID string
	Online    bool
	Linked    bool
}

type EventKind string

const (
	EventLinked         EventKind = "linked"
	EventPaired         EventKind = "paired"
	EventPairFailed     EventKind = "pair_failed"
	EventConnected      EventKind = "connected"
	EventDisconnected   EventKind = "disconnected"
	EventLoggedOut      EventKind = "logged_out"
	EventReauthRequired EventKind = "reauth_required"
	EventRestricted     EventKind = "restricted"
	EventDelivered      EventKind = "delivered"
	EventRead           EventKind = "read"
)

type Event struct {
	Kind              EventKind
	AccountID         string
	DeviceJID         string
	ProviderMessageID string
	Timestamp         time.Time
	Attempt           int
}

type EventHandler func(Event)

// Engine is deliberately narrower than the selected protocol library. The
// production implementation uses whatsmeow, but callers must not depend
// directly on library-specific socket or event types.
type Engine interface {
	Name() string
	SetEventHandler(EventHandler)
	Start(context.Context) error
	Ready(context.Context) error
	Pair(context.Context, PairRequest) (PairResult, error)
	Connect(context.Context, AccountConfig) error
	Disconnect(context.Context, string) error
	Logout(context.Context, string) error
	Send(context.Context, Message) (SendResult, error)
	Status(context.Context, string) (AccountStatus, error)
	Close(context.Context) error
}
