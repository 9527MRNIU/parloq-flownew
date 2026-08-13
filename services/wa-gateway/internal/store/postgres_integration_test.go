package store

import (
	"context"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
)

func TestPostgresRejectsStaleMessageFence(t *testing.T) {
	databaseURL := os.Getenv("WA_GATEWAY_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("WA_GATEWAY_TEST_DATABASE_URL is not set")
	}
	repository, err := NewPostgres(databaseURL, 4)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err = repository.Migrate(ctx); err != nil {
		t.Fatal(err)
	}

	suffix := time.Now().UnixNano()
	accountID := fmt.Sprintf("fence_test_%d", suffix)
	phone := fmt.Sprintf("+1999%08d", suffix%100000000)
	if _, err = repository.CreateAccount(ctx, model.Account{
		ID: accountID, PhoneE164: phone, State: "unpaired",
	}); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = repository.db.ExecContext(context.Background(),
			`DELETE FROM wa_gateway.accounts WHERE id=$1`, accountID)
	}()
	if err = repository.AdvanceAccountFence(ctx, accountID, 10); err != nil {
		t.Fatal(err)
	}

	message := model.Message{
		ID:            fmt.Sprintf("fence-message-%d", suffix),
		AccountID:     accountID,
		RecipientE164: "+14155550123",
		Status:        model.MessageQueued,
		QueuedAt:      time.Now().UTC(),
	}
	if _, _, err = repository.CreateMessage(ctx, message, 9); !errors.Is(err, ErrNotFound) {
		t.Fatalf("stale create error = %v, want ErrNotFound", err)
	}
	if _, created, createErr := repository.CreateMessage(ctx, message, 10); createErr != nil || !created {
		t.Fatalf("current create = (%v, %v), want created", created, createErr)
	}
	providerID := fmt.Sprintf("provider-%d", suffix)
	if _, err = repository.MarkMessageSent(ctx, message.ID, providerID, 9); !errors.Is(err, ErrNotFound) {
		t.Fatalf("stale sent error = %v, want ErrNotFound", err)
	}
	if _, err = repository.MarkMessageSent(ctx, message.ID, providerID, 10); err != nil {
		t.Fatal(err)
	}
	if _, changed, deliveryErr := repository.MarkMessageDeliveredByProviderID(
		ctx, providerID, accountID, 9,
	); deliveryErr != nil || changed {
		t.Fatalf("stale delivery = (%v, %v), want unchanged", changed, deliveryErr)
	}
	if _, changed, deliveryErr := repository.MarkMessageDeliveredByProviderID(
		ctx, providerID, accountID, 10,
	); deliveryErr != nil || !changed {
		t.Fatalf("current delivery = (%v, %v), want changed", changed, deliveryErr)
	}
}
