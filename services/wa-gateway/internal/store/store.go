package store

import (
	"context"
	"errors"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
)

var (
	ErrNotFound = errors.New("record not found")
	ErrConflict = errors.New("record already exists")
)

type Repository interface {
	Ready(context.Context) error
	Migrate(context.Context) error
	CreateAccount(context.Context, model.Account) (model.Account, error)
	ListAccounts(context.Context) ([]model.Account, error)
	GetAccount(context.Context, string) (model.Account, error)
	UpdateAccount(context.Context, string, string, string, bool, int64) (model.Account, error)
	UpdateAccountPhone(context.Context, string, string, int64) (model.Account, error)
	UpdateAccountState(context.Context, string, string, bool, int64) (model.Account, error)
	SetAccountDevice(context.Context, string, string, string, bool, int64) (model.Account, error)
	ClearAccountDevice(context.Context, string, int64) (model.Account, error)
	AdvanceAccountFence(context.Context, string, int64) error
	CreateMessage(context.Context, model.Message, int64) (model.Message, bool, error)
	GetMessage(context.Context, string) (model.Message, error)
	MarkMessageSent(context.Context, string, string, int64) (model.Message, error)
	MarkMessageDeliveredByProviderID(context.Context, string, string, int64) (model.Message, bool, error)
	MarkMessageFailed(context.Context, string, string, int64) (model.Message, error)
}
