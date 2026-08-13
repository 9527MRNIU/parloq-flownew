// Package whatsmeow implements the production WhatsApp Web protocol adapter.
// It intentionally subscribes only to connection and receipt events; inbound
// message bodies and media are never stored or forwarded.
package whatsmeow

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"

	_ "github.com/jackc/pgx/v5/stdlib"
	wm "go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	wmstore "go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"

	enginecontract "github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	gatewaystore "github.com/parloq/parloq-flow/services/wa-gateway/internal/store"
)

type managedClient struct {
	client            *wm.Client
	device            *wmstore.Device
	intentionalLogout atomic.Bool
}

type Engine struct {
	databaseURL string
	ownedDB     bool
	mu          sync.RWMutex
	db          *sql.DB
	container   *sqlstore.Container
	clients     map[string]*managedClient
	handler     enginecontract.EventHandler
	started     bool
}

func New(databaseURL string) *Engine {
	return &Engine{databaseURL: databaseURL, ownedDB: true, clients: make(map[string]*managedClient)}
}

func NewWithDB(database *sql.DB) *Engine {
	return &Engine{db: database, clients: make(map[string]*managedClient)}
}

func (e *Engine) Name() string { return "whatsmeow" }

func (e *Engine) SetEventHandler(handler enginecontract.EventHandler) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.handler = handler
}

func (e *Engine) Start(ctx context.Context) error {
	e.mu.RLock()
	db := e.db
	e.mu.RUnlock()
	var err error
	if db == nil {
		normalized, err := gatewaystore.NormalizePostgresURL(e.databaseURL)
		if err != nil {
			return err
		}
		db, err = sql.Open("pgx", normalized)
		if err != nil {
			return err
		}
		db.SetMaxOpenConns(50)
		db.SetMaxIdleConns(10)
	}
	if err = db.PingContext(ctx); err != nil {
		if e.ownedDB {
			_ = db.Close()
		}
		return fmt.Errorf("connect whatsmeow store: %w", err)
	}
	container := sqlstore.NewWithDB(db, "postgres", waLog.Noop)
	if err = container.Upgrade(ctx); err != nil {
		if e.ownedDB {
			_ = db.Close()
		}
		return fmt.Errorf("upgrade whatsmeow store: %w", err)
	}
	e.mu.Lock()
	e.db = db
	e.container = container
	e.started = true
	e.mu.Unlock()
	return nil
}

func (e *Engine) Ready(ctx context.Context) error {
	e.mu.RLock()
	db := e.db
	started := e.started
	e.mu.RUnlock()
	if !started || db == nil {
		return errors.New("whatsmeow engine is not started")
	}
	return db.PingContext(ctx)
}

func (e *Engine) Pair(ctx context.Context, request enginecontract.PairRequest) (enginecontract.PairResult, error) {
	if request.AccountID == "" {
		return enginecontract.PairResult{}, errors.New("account ID is required")
	}
	phone, err := normalizePhone(request.PhoneE164)
	if err != nil {
		return enginecontract.PairResult{}, err
	}
	e.mu.Lock()
	if _, exists := e.clients[request.AccountID]; exists {
		e.mu.Unlock()
		return enginecontract.PairResult{}, errors.New("account already has an active client")
	}
	container := e.container
	e.mu.Unlock()
	if container == nil {
		return enginecontract.PairResult{}, errors.New("whatsmeow store is not ready")
	}
	device := container.NewDevice()
	client, err := e.makeClient(request.AccountID, device, request.ProxyURL)
	if err != nil {
		return enginecontract.PairResult{}, err
	}
	qrChannel, err := client.GetQRChannel(ctx)
	if err != nil {
		return enginecontract.PairResult{}, fmt.Errorf("prepare pairing channel: %w", err)
	}
	e.mu.Lock()
	e.clients[request.AccountID] = &managedClient{client: client, device: device}
	e.mu.Unlock()
	if err = client.ConnectContext(ctx); err != nil {
		e.removeClient(request.AccountID, client)
		return enginecontract.PairResult{}, fmt.Errorf("connect pairing socket: %w", err)
	}

	waitContext, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	select {
	case <-waitContext.Done():
		client.Disconnect()
		e.removeClient(request.AccountID, client)
		return enginecontract.PairResult{}, errors.New("pairing socket did not become ready")
	case item, ok := <-qrChannel:
		if !ok || item.Error != nil {
			client.Disconnect()
			e.removeClient(request.AccountID, client)
			if item.Error != nil {
				return enginecontract.PairResult{}, fmt.Errorf("pairing channel: %w", item.Error)
			}
			return enginecontract.PairResult{}, errors.New("pairing channel closed")
		}
	}
	code, err := client.PairPhone(ctx, phone, true, wm.PairClientChrome, "Chrome (Linux)")
	if err != nil {
		client.Disconnect()
		e.removeClient(request.AccountID, client)
		return enginecontract.PairResult{}, fmt.Errorf("request pairing code: %w", err)
	}
	return enginecontract.PairResult{
		AccountID: request.AccountID,
		Code:      code,
		ExpiresAt: time.Now().UTC().Add(160 * time.Second),
	}, nil
}

func (e *Engine) Connect(ctx context.Context, config enginecontract.AccountConfig) error {
	e.mu.RLock()
	managed := e.clients[config.AccountID]
	container := e.container
	e.mu.RUnlock()
	if managed != nil {
		if managed.client.IsLoggedIn() {
			return nil
		}
		if !managed.client.IsConnected() {
			if err := managed.client.ConnectContext(ctx); err != nil {
				return err
			}
		}
		return waitUntilLoggedIn(ctx, managed.client)
	}
	if config.DeviceJID == "" {
		return enginecontract.ErrAccountNotFound
	}
	jid, err := types.ParseJID(config.DeviceJID)
	if err != nil {
		return fmt.Errorf("parse persisted device JID: %w", err)
	}
	if container == nil {
		return errors.New("whatsmeow store is not ready")
	}
	device, err := container.GetDevice(ctx, jid)
	if err != nil {
		return fmt.Errorf("load persisted device: %w", err)
	}
	if device == nil {
		return enginecontract.ErrAccountNotFound
	}
	client, err := e.makeClient(config.AccountID, device, config.ProxyURL)
	if err != nil {
		return err
	}
	e.mu.Lock()
	if existing := e.clients[config.AccountID]; existing != nil {
		e.mu.Unlock()
		if !existing.client.IsConnected() {
			if err = existing.client.ConnectContext(ctx); err != nil {
				return err
			}
		}
		return waitUntilLoggedIn(ctx, existing.client)
	}
	e.clients[config.AccountID] = &managedClient{client: client, device: device}
	e.mu.Unlock()
	if err = client.ConnectContext(ctx); err != nil {
		e.removeClient(config.AccountID, client)
		return err
	}
	if err = waitUntilLoggedIn(ctx, client); err != nil {
		client.Disconnect()
		e.removeClient(config.AccountID, client)
		return err
	}
	return nil
}

func (e *Engine) Disconnect(_ context.Context, accountID string) error {
	e.mu.RLock()
	managed := e.clients[accountID]
	e.mu.RUnlock()
	if managed == nil {
		return enginecontract.ErrAccountNotFound
	}
	managed.client.Disconnect()
	return nil
}

func (e *Engine) Logout(ctx context.Context, accountID string) error {
	e.mu.RLock()
	managed := e.clients[accountID]
	e.mu.RUnlock()
	if managed == nil {
		return enginecontract.ErrAccountNotFound
	}
	if !managed.client.IsConnected() {
		if err := managed.client.ConnectContext(ctx); err != nil {
			return fmt.Errorf("connect before logout: %w", err)
		}
	}
	if err := waitUntilLoggedIn(ctx, managed.client); err != nil {
		return fmt.Errorf("authenticate before logout: %w", err)
	}
	managed.intentionalLogout.Store(true)
	if err := managed.client.Logout(ctx); err != nil {
		managed.intentionalLogout.Store(false)
		return err
	}
	e.removeClient(accountID, managed.client)
	return nil
}

func (e *Engine) Send(ctx context.Context, message enginecontract.Message) (enginecontract.SendResult, error) {
	e.mu.RLock()
	managed := e.clients[message.AccountID]
	e.mu.RUnlock()
	if managed == nil {
		return enginecontract.SendResult{}, enginecontract.ErrAccountNotFound
	}
	if !managed.client.IsLoggedIn() {
		return enginecontract.SendResult{}, enginecontract.ErrAccountOffline
	}
	phone, err := normalizePhone(message.ToE164)
	if err != nil {
		return enginecontract.SendResult{}, err
	}
	response, err := managed.client.SendMessage(ctx,
		types.NewJID(phone, types.DefaultUserServer),
		&waE2E.Message{Conversation: proto.String(message.Text)},
		wm.SendRequestExtra{ID: managed.client.GenerateMessageID()},
	)
	if err != nil {
		return enginecontract.SendResult{}, err
	}
	return enginecontract.SendResult{
		ProviderMessageID: string(response.ID),
		ServerAcceptedAt:  response.Timestamp.UTC(),
	}, nil
}

func (e *Engine) Status(_ context.Context, accountID string) (enginecontract.AccountStatus, error) {
	e.mu.RLock()
	managed := e.clients[accountID]
	e.mu.RUnlock()
	if managed == nil {
		return enginecontract.AccountStatus{}, enginecontract.ErrAccountNotFound
	}
	return enginecontract.AccountStatus{
		AccountID: accountID,
		Online:    managed.client.IsLoggedIn(),
		Linked:    managed.device.ID != nil,
	}, nil
}

func (e *Engine) Close(context.Context) error {
	e.mu.Lock()
	clients := e.clients
	e.clients = make(map[string]*managedClient)
	db := e.db
	e.db = nil
	e.container = nil
	e.started = false
	e.mu.Unlock()
	for _, managed := range clients {
		managed.client.Disconnect()
	}
	if db != nil && e.ownedDB {
		return db.Close()
	}
	return nil
}

func (e *Engine) makeClient(accountID string, device *wmstore.Device, proxyURL string) (*wm.Client, error) {
	if strings.TrimSpace(proxyURL) == "" {
		return nil, errors.New("account proxy is required for the whatsmeow engine")
	}
	client := wm.NewClient(device, waLog.Noop)
	client.EnableAutoReconnect = true
	client.InitialAutoReconnect = true
	client.ManualHistorySyncDownload = false
	client.DisableManualHistorySyncReceipt = true
	client.EnableDecryptedEventBuffer = false
	if err := validateProxyURL(proxyURL); err != nil {
		return nil, err
	}
	if err := client.SetProxyAddress(proxyURL); err != nil {
		return nil, errors.New("apply account proxy configuration")
	}
	client.AddEventHandler(func(rawEvent any) {
		e.handleEvent(accountID, client, rawEvent)
	})
	return client, nil
}

func (e *Engine) handleEvent(accountID string, client *wm.Client, rawEvent any) {
	now := time.Now().UTC()
	switch event := rawEvent.(type) {
	case *events.PairSuccess:
		deviceJID := event.ID.String()
		if client.Store.ID != nil {
			deviceJID = client.Store.ID.String()
		}
		e.emit(enginecontract.Event{Kind: enginecontract.EventPaired, AccountID: accountID, DeviceJID: deviceJID, Timestamp: now})
	case *events.PairError:
		e.emit(enginecontract.Event{Kind: enginecontract.EventPairFailed, AccountID: accountID, Timestamp: now})
	case *events.Connected:
		deviceJID := ""
		if client.Store.ID != nil {
			deviceJID = client.Store.ID.String()
		}
		e.emit(enginecontract.Event{Kind: enginecontract.EventConnected, AccountID: accountID, DeviceJID: deviceJID, Timestamp: now})
	case *events.Disconnected:
		e.emit(enginecontract.Event{Kind: enginecontract.EventDisconnected, AccountID: accountID, Timestamp: now})
	case *events.LoggedOut:
		if !e.intentionalLogout(accountID, client) {
			e.emit(enginecontract.Event{Kind: enginecontract.EventReauthRequired, AccountID: accountID, Timestamp: now})
		}
	case *events.TemporaryBan:
		e.emit(enginecontract.Event{Kind: enginecontract.EventRestricted, AccountID: accountID, Timestamp: now})
	case *events.ConnectFailure:
		if event.Reason.IsLoggedOut() {
			e.emit(enginecontract.Event{Kind: enginecontract.EventReauthRequired, AccountID: accountID, Timestamp: now})
		}
	case *events.Receipt:
		kind := enginecontract.EventKind("")
		switch event.Type {
		case types.ReceiptTypeDelivered:
			kind = enginecontract.EventDelivered
		case types.ReceiptTypeRead, types.ReceiptTypeReadSelf:
			kind = enginecontract.EventRead
		default:
			return
		}
		for _, messageID := range event.MessageIDs {
			e.emit(enginecontract.Event{
				Kind:              kind,
				AccountID:         accountID,
				ProviderMessageID: string(messageID),
				Timestamp:         event.Timestamp.UTC(),
			})
		}
	}
}

func (e *Engine) intentionalLogout(accountID string, client *wm.Client) bool {
	e.mu.RLock()
	managed := e.clients[accountID]
	e.mu.RUnlock()
	return managed != nil && managed.client == client && managed.intentionalLogout.Load()
}

func (e *Engine) emit(event enginecontract.Event) {
	e.mu.RLock()
	handler := e.handler
	e.mu.RUnlock()
	if handler != nil {
		handler(event)
	}
}

func (e *Engine) removeClient(accountID string, client *wm.Client) {
	e.mu.Lock()
	if managed := e.clients[accountID]; managed != nil && managed.client == client {
		delete(e.clients, accountID)
	}
	e.mu.Unlock()
}

func normalizePhone(phone string) (string, error) {
	phone = strings.TrimSpace(phone)
	phone = strings.TrimPrefix(phone, "+")
	if len(phone) < 7 || len(phone) > 15 {
		return "", errors.New("phone number must contain 7 to 15 digits in E.164 format")
	}
	for _, character := range phone {
		if !unicode.IsDigit(character) || character > unicode.MaxASCII {
			return "", errors.New("phone number must contain digits only")
		}
	}
	return phone, nil
}

func validateProxyURL(raw string) error {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" {
		return errors.New("proxy must be a valid HTTP or SOCKS5 URL")
	}
	switch strings.ToLower(parsed.Scheme) {
	case "http", "https", "socks5", "socks5h":
		return nil
	default:
		return errors.New("proxy scheme must be http, https, socks5 or socks5h")
	}
}

func waitUntilLoggedIn(ctx context.Context, client *wm.Client) error {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		if client.IsLoggedIn() {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("wait for authenticated connection: %w", ctx.Err())
		case <-ticker.C:
		}
	}
}
