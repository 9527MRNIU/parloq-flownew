package runtime

import (
	"context"
	"sync"
	"testing"
	"time"
)

func TestTenQPSPacing(t *testing.T) {
	gate := NewRateGate(10)
	started := time.Now()
	for index := 0; index < 10; index++ {
		if err := gate.Wait(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	elapsed := time.Since(started)
	if elapsed < 850*time.Millisecond {
		t.Fatalf("10 sends completed too quickly: %s", elapsed)
	}
	if elapsed > 2*time.Second {
		t.Fatalf("10 sends completed too slowly: %s", elapsed)
	}
}

func TestMockScheduleBaselineForOneThousandAccounts(t *testing.T) {
	if testing.Short() {
		t.Skip("load baseline disabled in short mode")
	}
	const accounts = 1000
	const sendsPerAccount = 10
	started := time.Now()
	var waitGroup sync.WaitGroup
	waitGroup.Add(accounts)
	for accountIndex := 0; accountIndex < accounts; accountIndex++ {
		go func() {
			defer waitGroup.Done()
			gate := NewRateGate(10)
			for messageIndex := 0; messageIndex < sendsPerAccount; messageIndex++ {
				if err := gate.Wait(context.Background()); err != nil {
					t.Errorf("wait: %v", err)
					return
				}
			}
		}()
	}
	waitGroup.Wait()
	elapsed := time.Since(started)
	if elapsed < 850*time.Millisecond {
		t.Fatalf("10,000 dispatches bypassed 10 QPS account pacing: %s", elapsed)
	}
	if elapsed > 5*time.Second {
		t.Fatalf("10,000 logical dispatches exceeded baseline: %s", elapsed)
	}
	t.Logf("scheduled %d logical messages across %d accounts in %s", accounts*sendsPerAccount, accounts, elapsed)
}
