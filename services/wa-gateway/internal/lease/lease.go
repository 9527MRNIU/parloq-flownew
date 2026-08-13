package lease

import (
	"context"
	"errors"
	"strconv"
	"sync"
	"time"
)

var ErrUnavailable = errors.New("account lease is unavailable")

type Lease struct {
	AccountID string
	Value     string
	Epoch     int64
}

type Manager interface {
	Ready(context.Context) error
	Acquire(context.Context, string) (Lease, error)
	Renew(context.Context, Lease) (bool, error)
	Release(context.Context, Lease) (bool, error)
}

// MemoryManager is used only by isolated tests. Docker and production use the
// Redis implementation so ownership survives process pauses and crashes.
type MemoryManager struct {
	mu     sync.Mutex
	epoch  int64
	leases map[string]Lease
}

func NewMemoryManager() *MemoryManager {
	return &MemoryManager{leases: make(map[string]Lease)}
}

func (m *MemoryManager) Ready(context.Context) error { return nil }

func (m *MemoryManager) Acquire(_ context.Context, accountID string) (Lease, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, exists := m.leases[accountID]; exists {
		return Lease{}, ErrUnavailable
	}
	m.epoch++
	value := "memory:" + strconv.FormatInt(m.epoch, 10)
	current := Lease{AccountID: accountID, Value: value, Epoch: m.epoch}
	m.leases[accountID] = current
	return current, nil
}

func (m *MemoryManager) Renew(_ context.Context, current Lease) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	stored, ok := m.leases[current.AccountID]
	return ok && stored.Value == current.Value, nil
}

func (m *MemoryManager) Release(_ context.Context, current Lease) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	stored, ok := m.leases[current.AccountID]
	if !ok || stored.Value != current.Value {
		return false, nil
	}
	delete(m.leases, current.AccountID)
	return true, nil
}

func ValidateTiming(ttl, renew time.Duration) error {
	if ttl < 5*time.Second {
		return errors.New("lease TTL must be at least 5 seconds")
	}
	if renew <= 0 || renew >= ttl {
		return errors.New("lease renew interval must be positive and less than TTL")
	}
	return nil
}
