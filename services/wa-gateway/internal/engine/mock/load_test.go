package mock_test

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	enginecontract "github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine/mock"
	gatewayruntime "github.com/parloq/parloq-flow/services/wa-gateway/internal/runtime"
)

func TestOneThousandLogicalAccountsAtTenQPS(t *testing.T) {
	if testing.Short() {
		t.Skip("mock load baseline disabled in short mode")
	}
	const accountCount = 1000
	const messagesPerAccount = 10
	ctx := context.Background()
	protocol := mock.New()
	if err := protocol.Start(ctx); err != nil {
		t.Fatal(err)
	}
	defer protocol.Close(ctx)

	for accountIndex := 0; accountIndex < accountCount; accountIndex++ {
		accountID := fmt.Sprintf("load-%04d", accountIndex)
		if _, err := protocol.Pair(ctx, enginecontract.PairRequest{AccountID: accountID}); err != nil {
			t.Fatalf("pair %s: %v", accountID, err)
		}
	}

	started := time.Now()
	var failures atomic.Int64
	var waitGroup sync.WaitGroup
	waitGroup.Add(accountCount)
	for accountIndex := 0; accountIndex < accountCount; accountIndex++ {
		accountID := fmt.Sprintf("load-%04d", accountIndex)
		go func() {
			defer waitGroup.Done()
			gate := gatewayruntime.NewRateGate(10)
			for messageIndex := 0; messageIndex < messagesPerAccount; messageIndex++ {
				if err := gate.Wait(ctx); err != nil {
					failures.Add(1)
					return
				}
				result, err := protocol.Send(ctx, enginecontract.Message{
					RequestID: fmt.Sprintf("%s-%02d", accountID, messageIndex),
					AccountID: accountID,
					ToE164:    "+14155550123",
					Text:      "load baseline",
				})
				if err != nil || result.ProviderMessageID == "" {
					failures.Add(1)
				}
			}
		}()
	}
	waitGroup.Wait()
	elapsed := time.Since(started)
	if failures.Load() != 0 {
		t.Fatalf("mock sends failed: %d", failures.Load())
	}
	if elapsed < 850*time.Millisecond || elapsed > 5*time.Second {
		t.Fatalf("10,000 mock sends completed outside baseline window: %s", elapsed)
	}
	t.Logf("mock sent %d messages across %d logical accounts in %s", accountCount*messagesPerAccount, accountCount, elapsed)
}
