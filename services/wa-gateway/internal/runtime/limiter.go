package runtime

import (
	"context"
	"sync"
	"time"
)

// RateGate is a strict single-account pacer. It permits no burst above the
// configured QPS, which is intentionally conservative for WhatsApp accounts.
type RateGate struct {
	mu       sync.Mutex
	interval time.Duration
	next     time.Time
}

func NewRateGate(qps int) *RateGate {
	if qps < 1 {
		qps = 1
	}
	return &RateGate{interval: time.Second / time.Duration(qps)}
}

func (g *RateGate) Wait(ctx context.Context) error {
	g.mu.Lock()
	now := time.Now()
	wait := time.Duration(0)
	if now.Before(g.next) {
		wait = time.Until(g.next)
		g.next = g.next.Add(g.interval)
	} else {
		g.next = now.Add(g.interval)
	}
	g.mu.Unlock()
	if wait <= 0 {
		return nil
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
