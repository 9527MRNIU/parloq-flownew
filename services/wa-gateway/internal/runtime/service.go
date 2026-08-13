package runtime

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/account"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/lease"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/metrics"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/store"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/webhook"
)

var (
	ErrQueueFull       = errors.New("account send queue is full")
	ErrInvalidArgument = errors.New("invalid argument")
	ErrConflict        = errors.New("resource conflict")
	ErrProtocol        = errors.New("protocol operation failed")
)

type Config struct {
	LeaseRenewInterval time.Duration
	SendQPS            int
	QueueSize          int
	ConcurrentSends    int
	SendTimeout        time.Duration
	RestoreConcurrency int
}

type CreateAccountRequest struct {
	ID        string `json:"id"`
	PhoneE164 string `json:"phoneE164"`
	ProxyURL  string `json:"proxyUrl"`
}

type PairingCodeRequest struct {
	PhoneE164 string `json:"phoneE164"`
}

type UpdateAccountRequest struct {
	ProxyURL    *string `json:"proxyUrl"`
	PhoneE164   *string `json:"phoneE164"`
	AutoConnect *bool   `json:"autoConnect"`
}

type SendTextRequest struct {
	MessageID string `json:"messageId"`
	ToE164    string `json:"toE164"`
	Text      string `json:"text"`
}

type sendJob struct {
	message model.Message
	text    string
	epoch   int64
}

type accountWorker struct {
	accountID string
	lease     lease.Lease
	queue     chan sendJob
	gate      *RateGate
	context   context.Context
	cancel    context.CancelFunc
	done      chan struct{}
	active    atomic.Bool
}

type Service struct {
	repository store.Repository
	leases     lease.Manager
	engine     engine.Engine
	webhooks   *webhook.Client
	metrics    *metrics.Registry
	logger     *slog.Logger
	config     Config

	rootContext context.Context
	cancelRoot  context.CancelFunc
	sendSlots   chan struct{}
	mu          sync.RWMutex
	workers     map[string]*accountWorker
}

func New(
	repository store.Repository,
	leases lease.Manager,
	protocol engine.Engine,
	webhooks *webhook.Client,
	metricRegistry *metrics.Registry,
	logger *slog.Logger,
	config Config,
) *Service {
	if config.SendQPS < 1 {
		config.SendQPS = 10
	}
	if config.QueueSize < 1 {
		config.QueueSize = 1000
	}
	if config.ConcurrentSends < 1 {
		config.ConcurrentSends = 100
	}
	if config.SendTimeout <= 0 {
		config.SendTimeout = 30 * time.Second
	}
	if config.RestoreConcurrency < 1 {
		config.RestoreConcurrency = 25
	}
	rootContext, cancelRoot := context.WithCancel(context.Background())
	service := &Service{
		repository:  repository,
		leases:      leases,
		engine:      protocol,
		webhooks:    webhooks,
		metrics:     metricRegistry,
		logger:      logger,
		config:      config,
		rootContext: rootContext,
		cancelRoot:  cancelRoot,
		sendSlots:   make(chan struct{}, config.ConcurrentSends),
		workers:     make(map[string]*accountWorker),
	}
	protocol.SetEventHandler(func(event engine.Event) {
		go service.handleEngineEvent(event)
	})
	return service
}

func (s *Service) Start(ctx context.Context) error {
	if err := s.repository.Migrate(ctx); err != nil {
		return fmt.Errorf("migrate gateway store: %w", err)
	}
	if err := s.engine.Start(ctx); err != nil {
		return err
	}
	accounts, err := s.repository.ListAccounts(ctx)
	if err != nil {
		return err
	}
	semaphore := make(chan struct{}, s.config.RestoreConcurrency)
	for _, current := range accounts {
		if !current.AutoConnect || current.DeviceJID == "" {
			continue
		}
		accountCopy := current
		go func() {
			semaphore <- struct{}{}
			defer func() { <-semaphore }()
			restoreContext, cancel := context.WithTimeout(s.rootContext, 45*time.Second)
			defer cancel()
			if _, restoreErr := s.connect(restoreContext, accountCopy, true); restoreErr != nil {
				s.logger.Warn("account_restore_failed", "account_id", accountCopy.ID, "error", restoreErr)
			}
		}()
	}
	return nil
}

func (s *Service) Ready(ctx context.Context) error {
	if err := s.repository.Ready(ctx); err != nil {
		return err
	}
	if err := s.leases.Ready(ctx); err != nil {
		return err
	}
	return s.engine.Ready(ctx)
}

func (s *Service) EngineName() string { return s.engine.Name() }

func (s *Service) Close(ctx context.Context) error {
	s.cancelRoot()
	s.mu.RLock()
	workers := make([]*accountWorker, 0, len(s.workers))
	for _, worker := range s.workers {
		workers = append(workers, worker)
	}
	s.mu.RUnlock()
	for _, worker := range workers {
		s.stopWorker(ctx, worker, "gateway_shutdown")
	}
	return s.engine.Close(ctx)
}

func (s *Service) CreateAccount(ctx context.Context, request CreateAccountRequest) (model.Account, error) {
	phone, err := normalizeE164(request.PhoneE164)
	if err != nil {
		return model.Account{}, err
	}
	if err = validateProxy(request.ProxyURL); err != nil {
		return model.Account{}, err
	}
	id := strings.TrimSpace(request.ID)
	if id == "" {
		id = "wa_" + randomID(12)
	}
	if len(id) > 80 {
		return model.Account{}, fmt.Errorf("%w: account id is too long", ErrInvalidArgument)
	}
	if !validIdentifier(id) {
		return model.Account{}, fmt.Errorf("%w: account id may contain only letters, numbers, underscore, dash and dot", ErrInvalidArgument)
	}
	created, err := s.repository.CreateAccount(ctx, model.Account{
		ID:        id,
		PhoneE164: phone,
		ProxyURL:  strings.TrimSpace(request.ProxyURL),
		State:     string(account.StateUnpaired),
	})
	if err != nil {
		return model.Account{}, err
	}
	s.metrics.AccountsCreated.Add(1)
	return publicAccount(created), nil
}

func (s *Service) ListAccounts(ctx context.Context) ([]model.Account, error) {
	accounts, err := s.repository.ListAccounts(ctx)
	if err != nil {
		return nil, err
	}
	for index := range accounts {
		accounts[index] = publicAccount(accounts[index])
	}
	return accounts, nil
}

func (s *Service) GetAccount(ctx context.Context, id string) (model.Account, error) {
	current, err := s.repository.GetAccount(ctx, id)
	return publicAccount(current), err
}

func (s *Service) UpdateAccount(
	ctx context.Context,
	id string,
	request UpdateAccountRequest,
) (model.Account, error) {
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return model.Account{}, err
	}
	phone := current.PhoneE164
	proxyURL := current.ProxyURL
	autoConnect := current.AutoConnect
	if request.PhoneE164 != nil {
		phone, err = normalizeE164(*request.PhoneE164)
		if err != nil {
			return model.Account{}, err
		}
	}
	if request.ProxyURL != nil {
		proxyURL = strings.TrimSpace(*request.ProxyURL)
		if err = validateProxy(proxyURL); err != nil {
			return model.Account{}, err
		}
	}
	if request.AutoConnect != nil {
		autoConnect = *request.AutoConnect
	}
	if phone == current.PhoneE164 && proxyURL == current.ProxyURL && autoConnect == current.AutoConnect {
		return publicAccount(current), nil
	}
	worker := s.worker(id)
	if configurationChangeRequiresDisconnect(
		current,
		worker != nil,
		phone != current.PhoneE164,
		proxyURL != current.ProxyURL,
	) {
		return model.Account{}, fmt.Errorf("%w: disconnect the account before changing its phone or proxy", ErrConflict)
	}
	if worker != nil {
		updated, updateErr := s.repository.UpdateAccount(ctx, id, phone, proxyURL, autoConnect, worker.lease.Epoch)
		return publicAccount(updated), updateErr
	}
	acquired, err := s.leases.Acquire(ctx, id)
	if err != nil {
		return model.Account{}, err
	}
	defer func() {
		_, _ = s.leases.Release(context.Background(), acquired)
	}()
	if err = s.repository.AdvanceAccountFence(ctx, id, acquired.Epoch); err != nil {
		return model.Account{}, err
	}
	updated, err := s.repository.UpdateAccount(ctx, id, phone, proxyURL, autoConnect, acquired.Epoch)
	return publicAccount(updated), err
}

func (s *Service) RequestPairingCode(
	ctx context.Context,
	id string,
	request PairingCodeRequest,
) (engine.PairResult, error) {
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return engine.PairResult{}, err
	}
	if current.DeviceJID != "" {
		return engine.PairResult{}, fmt.Errorf("%w: account is already paired; logout before pairing a different phone", ErrConflict)
	}
	if current.State == string(account.StatePairing) && s.worker(id) != nil {
		return engine.PairResult{}, fmt.Errorf("%w: account already has an active pairing session", ErrConflict)
	}
	phone := current.PhoneE164
	if strings.TrimSpace(request.PhoneE164) != "" {
		phone, err = normalizeE164(request.PhoneE164)
		if err != nil {
			return engine.PairResult{}, err
		}
	}
	worker, err := s.ensureWorker(ctx, current)
	if err != nil {
		return engine.PairResult{}, err
	}
	if phone != current.PhoneE164 {
		if current, err = s.repository.UpdateAccountPhone(ctx, id, phone, worker.lease.Epoch); err != nil {
			return engine.PairResult{}, err
		}
	}
	if _, err = s.repository.UpdateAccountState(ctx, id, string(account.StatePairing), false, worker.lease.Epoch); err != nil {
		return engine.PairResult{}, err
	}
	protocolContext, cancelProtocol := context.WithTimeout(ctx, 30*time.Second)
	defer cancelProtocol()
	result, err := s.engine.Pair(protocolContext, engine.PairRequest{
		AccountID: id,
		Method:    engine.PairMethodCode,
		PhoneE164: phone,
		ProxyURL:  current.ProxyURL,
	})
	if err != nil {
		_, _ = s.repository.UpdateAccountState(ctx, id, string(account.StateUnpaired), false, worker.lease.Epoch)
		s.stopWorker(ctx, worker, "pairing_failed")
		s.logger.Warn("pairing_code_failed", "account_id", id, "error_code", "pairing_failed")
		return engine.PairResult{}, fmt.Errorf("%w: unable to request a pairing code; verify the phone number, proxy and network", ErrProtocol)
	}
	s.metrics.PairingRequests.Add(1)
	if result.DeviceJID != "" {
		_, _ = s.repository.SetAccountDevice(ctx, id, result.DeviceJID, string(account.StateOnlineIdle), true, worker.lease.Epoch)
		s.markWorkerActive(worker)
	}
	return result, nil
}

func (s *Service) Connect(ctx context.Context, id string) (model.Account, error) {
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return model.Account{}, err
	}
	return s.connect(ctx, current, false)
}

func (s *Service) connect(ctx context.Context, current model.Account, restoring bool) (model.Account, error) {
	if current.DeviceJID == "" {
		return model.Account{}, fmt.Errorf("%w: account must be paired before connecting", ErrConflict)
	}
	worker, err := s.ensureWorker(ctx, current)
	if err != nil {
		return model.Account{}, err
	}
	if _, err = s.repository.UpdateAccountState(ctx, current.ID, string(account.StateWarming), true, worker.lease.Epoch); err != nil {
		return model.Account{}, err
	}
	protocolContext, cancelProtocol := context.WithTimeout(ctx, 45*time.Second)
	defer cancelProtocol()
	if err = s.engine.Connect(protocolContext, engine.AccountConfig{
		AccountID: current.ID,
		ProxyURL:  current.ProxyURL,
		DeviceJID: current.DeviceJID,
	}); err != nil {
		_, _ = s.repository.UpdateAccountState(ctx, current.ID, string(account.StateLinkedOffline), restoring, worker.lease.Epoch)
		s.stopWorker(ctx, worker, "connect_failed")
		s.logger.Warn("account_connect_failed", "account_id", current.ID, "error_code", "connect_failed")
		return model.Account{}, fmt.Errorf("%w: unable to connect the saved WhatsApp session", ErrProtocol)
	}
	updated, err := s.repository.UpdateAccountState(ctx, current.ID, string(account.StateOnlineIdle), true, worker.lease.Epoch)
	if err == nil {
		s.metrics.Connects.Add(1)
		s.markWorkerActive(worker)
	}
	return publicAccount(updated), err
}

func (s *Service) Disconnect(ctx context.Context, id string) (model.Account, error) {
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return model.Account{}, err
	}
	worker := s.worker(id)
	epoch := current.LeaseEpoch
	if worker != nil {
		epoch = worker.lease.Epoch
		if err = s.engine.Disconnect(ctx, id); err != nil && !errors.Is(err, engine.ErrAccountNotFound) {
			return model.Account{}, err
		}
		s.stopWorker(ctx, worker, "disconnected")
	}
	updated, err := s.repository.UpdateAccountState(ctx, id, string(account.StateLinkedOffline), false, epoch)
	if err == nil {
		s.metrics.Disconnects.Add(1)
		s.markWorkerInactive(worker)
	}
	return publicAccount(updated), err
}

func (s *Service) Logout(ctx context.Context, id string) (model.Account, error) {
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return model.Account{}, err
	}
	if current.DeviceJID == "" {
		return publicAccount(current), nil
	}
	worker, err := s.ensureWorker(ctx, current)
	if err != nil {
		return model.Account{}, err
	}
	protocolContext, cancelProtocol := context.WithTimeout(ctx, 45*time.Second)
	defer cancelProtocol()
	if err = s.engine.Logout(protocolContext, id); err != nil {
		s.logger.Warn("account_logout_failed", "account_id", id, "error_code", "logout_failed")
		return model.Account{}, fmt.Errorf("%w: WhatsApp did not confirm logout", ErrProtocol)
	}
	updated, err := s.repository.ClearAccountDevice(ctx, id, worker.lease.Epoch)
	s.markWorkerInactive(worker)
	s.stopWorker(ctx, worker, "logged_out")
	return publicAccount(updated), err
}

func (s *Service) SendText(ctx context.Context, id string, request SendTextRequest) (model.Message, error) {
	if strings.TrimSpace(request.MessageID) == "" || len(request.MessageID) > 128 {
		return model.Message{}, fmt.Errorf("%w: messageId is required and must be at most 128 characters", ErrInvalidArgument)
	}
	if !validMessageID(request.MessageID) {
		return model.Message{}, fmt.Errorf("%w: messageId contains unsupported characters", ErrInvalidArgument)
	}
	recipient, err := normalizeE164(request.ToE164)
	if err != nil {
		return model.Message{}, err
	}
	if strings.TrimSpace(request.Text) == "" || len([]rune(request.Text)) > 4096 {
		return model.Message{}, fmt.Errorf("%w: text is required and must be at most 4096 characters", ErrInvalidArgument)
	}
	current, err := s.repository.GetAccount(ctx, id)
	if err != nil {
		return model.Message{}, err
	}
	if current.State != string(account.StateOnlineIdle) && current.State != string(account.StateSending) {
		return model.Message{}, fmt.Errorf("%w: account is not online", ErrConflict)
	}
	worker := s.worker(id)
	if worker == nil {
		return model.Message{}, fmt.Errorf("%w: account has no active owner", ErrConflict)
	}
	now := time.Now().UTC()
	message, created, err := s.repository.CreateMessage(ctx, model.Message{
		ID:            request.MessageID,
		AccountID:     id,
		RecipientE164: recipient,
		Status:        model.MessageQueued,
		QueuedAt:      now,
	}, worker.lease.Epoch)
	if err != nil {
		return model.Message{}, err
	}
	if !created {
		if message.AccountID != id || message.RecipientE164 != recipient {
			return model.Message{}, fmt.Errorf("%w: messageId was already used for a different request", ErrConflict)
		}
		return message, nil
	}
	job := sendJob{message: message, text: request.Text, epoch: worker.lease.Epoch}
	select {
	case worker.queue <- job:
		s.metrics.MessagesQueued.Add(1)
		s.deliverWebhook(message)
		return message, nil
	default:
		failed, failErr := s.repository.MarkMessageFailed(ctx, message.ID, "queue_full", worker.lease.Epoch)
		if failErr == nil {
			s.deliverWebhook(failed)
		}
		return model.Message{}, ErrQueueFull
	}
}

func (s *Service) GetMessage(ctx context.Context, id string) (model.Message, error) {
	return s.repository.GetMessage(ctx, id)
}

func (s *Service) ensureWorker(ctx context.Context, current model.Account) (*accountWorker, error) {
	if existing := s.worker(current.ID); existing != nil {
		return existing, nil
	}
	acquired, err := s.leases.Acquire(ctx, current.ID)
	if err != nil {
		return nil, err
	}
	if err = s.repository.AdvanceAccountFence(ctx, current.ID, acquired.Epoch); err != nil {
		_, _ = s.leases.Release(ctx, acquired)
		return nil, err
	}
	workerContext, cancel := context.WithCancel(s.rootContext)
	worker := &accountWorker{
		accountID: current.ID,
		lease:     acquired,
		queue:     make(chan sendJob, s.config.QueueSize),
		gate:      NewRateGate(s.config.SendQPS),
		context:   workerContext,
		cancel:    cancel,
		done:      make(chan struct{}),
	}
	s.mu.Lock()
	if existing := s.workers[current.ID]; existing != nil {
		s.mu.Unlock()
		cancel()
		_, _ = s.leases.Release(ctx, acquired)
		return existing, nil
	}
	s.workers[current.ID] = worker
	s.mu.Unlock()
	go s.runWorker(worker)
	go s.renewLease(worker)
	return worker, nil
}

func (s *Service) runWorker(worker *accountWorker) {
	defer close(worker.done)
	for {
		select {
		case <-worker.context.Done():
			s.failQueuedJobs(worker, "account_owner_stopped")
			return
		case job := <-worker.queue:
			if err := worker.gate.Wait(worker.context); err != nil {
				s.failJob(job, "account_owner_stopped")
				continue
			}
			select {
			case s.sendSlots <- struct{}{}:
			case <-worker.context.Done():
				s.failJob(job, "account_owner_stopped")
				continue
			}
			s.sendJob(worker, job)
			<-s.sendSlots
		}
	}
}

func (s *Service) sendJob(worker *accountWorker, job sendJob) {
	ctx, cancel := context.WithTimeout(worker.context, s.config.SendTimeout)
	defer cancel()
	result, err := s.engine.Send(ctx, engine.Message{
		RequestID: job.message.ID,
		AccountID: job.message.AccountID,
		ToE164:    job.message.RecipientE164,
		Text:      job.text,
	})
	if err != nil {
		s.failJob(job, normalizeErrorCode(err))
		return
	}
	updated, err := s.repository.MarkMessageSent(ctx, job.message.ID, result.ProviderMessageID, job.epoch)
	if err != nil {
		s.logger.Warn("message_sent_state_failed", "message_id", job.message.ID, "error", err)
		return
	}
	s.metrics.MessagesSent.Add(1)
	s.deliverWebhook(updated)
}

func (s *Service) failJob(job sendJob, errorCode string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	updated, err := s.repository.MarkMessageFailed(ctx, job.message.ID, errorCode, job.epoch)
	if err == nil {
		s.metrics.MessagesFailed.Add(1)
		s.deliverWebhook(updated)
	}
}

func (s *Service) failQueuedJobs(worker *accountWorker, errorCode string) {
	for {
		select {
		case job := <-worker.queue:
			s.failJob(job, errorCode)
		default:
			return
		}
	}
}

func (s *Service) renewLease(worker *accountWorker) {
	ticker := time.NewTicker(s.config.LeaseRenewInterval)
	defer ticker.Stop()
	for {
		select {
		case <-worker.context.Done():
			return
		case <-ticker.C:
			ctx, cancel := context.WithTimeout(worker.context, s.config.LeaseRenewInterval)
			valid, err := s.leases.Renew(ctx, worker.lease)
			cancel()
			if err != nil || !valid {
				s.logger.Error("account_lease_lost", "account_id", worker.accountID, "error", err)
				s.markWorkerInactive(worker)
				worker.cancel()
				_ = s.engine.Disconnect(context.Background(), worker.accountID)
				s.removeWorker(worker)
				return
			}
		}
	}
}

func (s *Service) stopWorker(ctx context.Context, worker *accountWorker, reason string) {
	if worker == nil {
		return
	}
	worker.cancel()
	s.removeWorker(worker)
	select {
	case <-worker.done:
	case <-ctx.Done():
	}
	if _, err := s.leases.Release(context.Background(), worker.lease); err != nil {
		s.logger.Warn("account_lease_release_failed", "account_id", worker.accountID, "reason", reason, "error", err)
	}
}

func (s *Service) worker(accountID string) *accountWorker {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.workers[accountID]
}

func (s *Service) removeWorker(worker *accountWorker) {
	s.mu.Lock()
	if s.workers[worker.accountID] == worker {
		delete(s.workers, worker.accountID)
	}
	s.mu.Unlock()
}

func (s *Service) handleEngineEvent(event engine.Event) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	switch event.Kind {
	case engine.EventPaired:
		worker := s.worker(event.AccountID)
		if worker == nil || event.DeviceJID == "" {
			return
		}
		_, err := s.repository.SetAccountDevice(ctx, event.AccountID, event.DeviceJID, string(account.StateLinkedOffline), true, worker.lease.Epoch)
		if err != nil {
			s.logger.Warn("paired_account_persist_failed", "account_id", event.AccountID, "error", err)
		}
	case engine.EventPairFailed:
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		_, _ = s.repository.UpdateAccountState(ctx, event.AccountID, string(account.StateUnpaired), false, worker.lease.Epoch)
		s.stopWorker(ctx, worker, "pair_failed")
	case engine.EventConnected:
		worker := s.worker(event.AccountID)
		if worker == nil || event.DeviceJID == "" {
			return
		}
		_, err := s.repository.SetAccountDevice(ctx, event.AccountID, event.DeviceJID, string(account.StateOnlineIdle), true, worker.lease.Epoch)
		if err != nil {
			s.logger.Warn("connected_account_persist_failed", "account_id", event.AccountID, "error", err)
		} else {
			s.markWorkerActive(worker)
		}
	case engine.EventLinked:
		worker := s.worker(event.AccountID)
		if worker == nil || event.DeviceJID == "" {
			return
		}
		_, err := s.repository.SetAccountDevice(ctx, event.AccountID, event.DeviceJID, string(account.StateOnlineIdle), true, worker.lease.Epoch)
		if err != nil {
			s.logger.Warn("linked_account_persist_failed", "account_id", event.AccountID, "error", err)
		} else {
			s.markWorkerActive(worker)
		}
	case engine.EventDisconnected:
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		s.markWorkerInactive(worker)
		current, err := s.repository.GetAccount(ctx, event.AccountID)
		if err != nil {
			return
		}
		state := string(account.StateLinkedOffline)
		autoConnect := true
		if current.DeviceJID == "" {
			state = string(account.StateUnpaired)
			autoConnect = false
		}
		_, _ = s.repository.UpdateAccountState(ctx, event.AccountID, state, autoConnect, worker.lease.Epoch)
	case engine.EventLoggedOut:
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		_, _ = s.repository.ClearAccountDevice(ctx, event.AccountID, worker.lease.Epoch)
		s.markWorkerInactive(worker)
		s.stopWorker(ctx, worker, "remote_logout")
	case engine.EventReauthRequired:
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		_, _ = s.repository.SetAccountDevice(ctx, event.AccountID, "", string(account.StateReauthRequired), false, worker.lease.Epoch)
		s.markWorkerInactive(worker)
		s.stopWorker(ctx, worker, "reauth_required")
	case engine.EventRestricted:
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		_, _ = s.repository.UpdateAccountState(ctx, event.AccountID, string(account.StateRestricted), false, worker.lease.Epoch)
		s.markWorkerInactive(worker)
		s.stopWorker(ctx, worker, "restricted")
	case engine.EventDelivered, engine.EventRead:
		// Read receipts are deliberately collapsed to delivered. The control
		// plane exposes only one tick (sent) and two ticks (delivered).
		worker := s.worker(event.AccountID)
		if worker == nil {
			return
		}
		updated, changed, err := s.repository.MarkMessageDeliveredByProviderID(
			ctx,
			event.ProviderMessageID,
			event.AccountID,
			worker.lease.Epoch,
		)
		if err != nil {
			s.logger.Warn("delivery_receipt_persist_failed", "provider_message_id", event.ProviderMessageID, "error", err)
			return
		}
		if !changed && event.Attempt < 3 {
			// A very fast mock/provider receipt may beat the sent-state commit.
			event.Attempt++
			time.AfterFunc(time.Duration(event.Attempt)*100*time.Millisecond, func() {
				s.handleEngineEvent(event)
			})
			return
		}
		if !changed {
			return
		}
		s.metrics.Delivered.Add(1)
		s.deliverWebhook(updated)
	}
}

func (s *Service) deliverWebhook(message model.Message) {
	if s.webhooks == nil || !s.webhooks.Enabled() {
		return
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := s.webhooks.Deliver(ctx, message); err != nil {
			s.metrics.WebhookFailed.Add(1)
			s.logger.Warn("status_webhook_failed", "message_id", message.ID, "status", message.Status, "error", err)
		}
	}()
}

func publicAccount(current model.Account) model.Account {
	current.ProxyMasked = maskProxy(current.ProxyURL)
	current.ProxyURL = ""
	return current
}

func maskProxy(raw string) string {
	if raw == "" {
		return ""
	}
	parsed, err := url.Parse(raw)
	if err != nil {
		return "configured"
	}
	parsed.User = nil
	return parsed.String()
}

func validateProxy(raw string) error {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" {
		return fmt.Errorf("%w: proxyUrl must be a valid URL", ErrInvalidArgument)
	}
	switch strings.ToLower(parsed.Scheme) {
	case "http", "https", "socks5", "socks5h":
		return nil
	default:
		return fmt.Errorf("%w: proxyUrl scheme must be http, https, socks5 or socks5h", ErrInvalidArgument)
	}
}

func normalizeE164(raw string) (string, error) {
	value := strings.TrimPrefix(strings.TrimSpace(raw), "+")
	if len(value) < 7 || len(value) > 15 {
		return "", fmt.Errorf("%w: phone number must contain 7 to 15 digits", ErrInvalidArgument)
	}
	for _, character := range value {
		if !unicode.IsDigit(character) || character > unicode.MaxASCII {
			return "", fmt.Errorf("%w: phone number must contain digits only", ErrInvalidArgument)
		}
	}
	return "+" + value, nil
}

func randomID(bytesCount int) string {
	buffer := make([]byte, bytesCount)
	if _, err := rand.Read(buffer); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(buffer)
}

func normalizeErrorCode(err error) string {
	switch {
	case errors.Is(err, engine.ErrAccountOffline):
		return "account_offline"
	case errors.Is(err, engine.ErrAccountNotFound):
		return "account_session_missing"
	case errors.Is(err, context.DeadlineExceeded):
		return "send_timeout"
	default:
		return "send_failed"
	}
}

func (s *Service) markWorkerActive(worker *accountWorker) {
	if worker != nil && worker.active.CompareAndSwap(false, true) {
		s.metrics.ActiveAccounts.Add(1)
	}
}

func (s *Service) markWorkerInactive(worker *accountWorker) {
	if worker != nil && worker.active.CompareAndSwap(true, false) {
		s.metrics.ActiveAccounts.Add(-1)
	}
}

func validIdentifier(value string) bool {
	if value == "" {
		return false
	}
	for _, character := range value {
		if (character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			character == '_' || character == '-' || character == '.' {
			continue
		}
		return false
	}
	return true
}

func validMessageID(value string) bool {
	for _, character := range value {
		if (character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			character == '_' || character == '-' || character == '.' || character == ':' {
			continue
		}
		return false
	}
	return true
}

func configurationChangeRequiresDisconnect(
	current model.Account,
	workerPresent bool,
	phoneChanges bool,
	proxyChanges bool,
) bool {
	if !phoneChanges && !proxyChanges {
		return false
	}
	if workerPresent {
		return true
	}
	switch account.State(current.State) {
	case account.StatePairing, account.StateWarming, account.StateOnlineIdle, account.StateSending, account.StateDraining:
		return true
	default:
		return false
	}
}
