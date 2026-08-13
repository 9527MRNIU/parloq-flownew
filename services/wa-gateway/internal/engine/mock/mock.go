// Package mock provides a deterministic, dependency-free Engine for local
// control-plane development. It never contacts WhatsApp.
package mock

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"sync"
	"time"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
)

type account struct {
	linked bool
	online bool
}

type Engine struct {
	mu       sync.RWMutex
	started  bool
	accounts map[string]account
	handler  engine.EventHandler
}

func New() *Engine {
	return &Engine{accounts: make(map[string]account)}
}

func (e *Engine) Name() string { return "mock" }

func (e *Engine) SetEventHandler(handler engine.EventHandler) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.handler = handler
}

func (e *Engine) Start(context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.started = true
	return nil
}

func (e *Engine) Ready(context.Context) error {
	e.mu.RLock()
	defer e.mu.RUnlock()
	if !e.started {
		return errors.New("mock engine is not started")
	}
	return nil
}

func (e *Engine) Pair(_ context.Context, request engine.PairRequest) (engine.PairResult, error) {
	if request.AccountID == "" {
		return engine.PairResult{}, errors.New("account ID is required")
	}
	e.mu.Lock()
	e.accounts[request.AccountID] = account{linked: true, online: true}
	handler := e.handler
	e.mu.Unlock()
	deviceJID := "mock-" + request.AccountID + "@s.whatsapp.net"
	if handler != nil {
		handler(engine.Event{
			Kind:      engine.EventLinked,
			AccountID: request.AccountID,
			DeviceJID: deviceJID,
			Timestamp: time.Now().UTC(),
		})
	}

	return engine.PairResult{
		AccountID: request.AccountID,
		Code:      "0000-0000",
		ExpiresAt: time.Now().UTC().Add(3 * time.Minute),
		DeviceJID: deviceJID,
	}, nil
}

func (e *Engine) Connect(_ context.Context, config engine.AccountConfig) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	current, ok := e.accounts[config.AccountID]
	if !ok && config.DeviceJID != "" {
		current = account{linked: true}
		ok = true
	}
	if !ok || !current.linked {
		return engine.ErrAccountNotFound
	}
	current.online = true
	e.accounts[config.AccountID] = current
	return nil
}

func (e *Engine) Disconnect(_ context.Context, accountID string) error {
	e.mu.Lock()
	current, ok := e.accounts[accountID]
	if !ok {
		e.mu.Unlock()
		return engine.ErrAccountNotFound
	}
	current.online = false
	e.accounts[accountID] = current
	handler := e.handler
	e.mu.Unlock()
	if handler != nil {
		handler(engine.Event{Kind: engine.EventDisconnected, AccountID: accountID, Timestamp: time.Now().UTC()})
	}
	return nil
}

func (e *Engine) Logout(_ context.Context, accountID string) error {
	e.mu.Lock()
	if _, ok := e.accounts[accountID]; !ok {
		e.mu.Unlock()
		return engine.ErrAccountNotFound
	}
	delete(e.accounts, accountID)
	handler := e.handler
	e.mu.Unlock()
	if handler != nil {
		handler(engine.Event{Kind: engine.EventLoggedOut, AccountID: accountID, Timestamp: time.Now().UTC()})
	}
	return nil
}

func (e *Engine) Send(_ context.Context, message engine.Message) (engine.SendResult, error) {
	e.mu.RLock()
	current, ok := e.accounts[message.AccountID]
	e.mu.RUnlock()
	if !ok {
		return engine.SendResult{}, engine.ErrAccountNotFound
	}
	if !current.online {
		return engine.SendResult{}, engine.ErrAccountOffline
	}
	digest := sha256.Sum256([]byte(message.AccountID + "\x00" + message.RequestID))
	providerID := "mock-" + hex.EncodeToString(digest[:8])
	e.mu.RLock()
	handler := e.handler
	e.mu.RUnlock()
	if handler != nil {
		go func() {
			timer := time.NewTimer(10 * time.Millisecond)
			defer timer.Stop()
			<-timer.C
			handler(engine.Event{
				Kind:              engine.EventDelivered,
				AccountID:         message.AccountID,
				ProviderMessageID: providerID,
				Timestamp:         time.Now().UTC(),
			})
		}()
	}
	return engine.SendResult{
		ProviderMessageID: providerID,
		ServerAcceptedAt:  time.Now().UTC(),
	}, nil
}

func (e *Engine) Status(_ context.Context, accountID string) (engine.AccountStatus, error) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	current, ok := e.accounts[accountID]
	if !ok {
		return engine.AccountStatus{}, engine.ErrAccountNotFound
	}
	return engine.AccountStatus{
		AccountID: accountID,
		Online:    current.online,
		Linked:    current.linked,
	}, nil
}

func (e *Engine) Close(context.Context) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.started = false
	for accountID, current := range e.accounts {
		current.online = false
		e.accounts[accountID] = current
	}
	return nil
}
