package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgconn"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
)

const postgresSchema = `
CREATE SCHEMA IF NOT EXISTS wa_gateway;

CREATE TABLE IF NOT EXISTS wa_gateway.accounts (
    id TEXT PRIMARY KEY,
    phone_e164 TEXT NOT NULL,
    proxy_url TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    device_jid TEXT NOT NULL DEFAULT '',
    auto_connect BOOLEAN NOT NULL DEFAULT FALSE,
    lease_epoch BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS wa_gateway_accounts_restore_idx
    ON wa_gateway.accounts (auto_connect, state);
CREATE UNIQUE INDEX IF NOT EXISTS wa_gateway_accounts_phone_idx
    ON wa_gateway.accounts (phone_e164);

CREATE TABLE IF NOT EXISTS wa_gateway.messages (
    message_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES wa_gateway.accounts(id) ON DELETE CASCADE,
    recipient_e164 TEXT NOT NULL,
    provider_message_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    queued_at TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS wa_gateway_messages_provider_id_idx
    ON wa_gateway.messages(provider_message_id)
    WHERE provider_message_id <> '';
CREATE INDEX IF NOT EXISTS wa_gateway_messages_account_status_idx
    ON wa_gateway.messages(account_id, status, queued_at DESC);
`

type Postgres struct {
	db *sql.DB
}

func NewPostgres(databaseURL string, maxConnections int) (*Postgres, error) {
	normalized, err := NormalizePostgresURL(databaseURL)
	if err != nil {
		return nil, err
	}
	db, err := sql.Open("pgx", normalized)
	if err != nil {
		return nil, err
	}
	if maxConnections < 2 {
		maxConnections = 20
	}
	db.SetMaxOpenConns(maxConnections)
	db.SetMaxIdleConns(maxConnections / 2)
	db.SetConnMaxIdleTime(5 * time.Minute)
	db.SetConnMaxLifetime(30 * time.Minute)
	return &Postgres{db: db}, nil
}

func NormalizePostgresURL(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	raw = strings.Replace(raw, "postgresql+psycopg://", "postgresql://", 1)
	raw = strings.Replace(raw, "postgresql+asyncpg://", "postgresql://", 1)
	parsed, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("parse PostgreSQL URL: %w", err)
	}
	if parsed.Scheme != "postgres" && parsed.Scheme != "postgresql" {
		return "", fmt.Errorf("database URL must use postgres or postgresql")
	}
	if parsed.Host == "" {
		return "", fmt.Errorf("database URL host is required")
	}
	return parsed.String(), nil
}

func (p *Postgres) DB() *sql.DB { return p.db }

func (p *Postgres) Close() error { return p.db.Close() }

func (p *Postgres) Ready(ctx context.Context) error { return p.db.PingContext(ctx) }

func (p *Postgres) Migrate(ctx context.Context) error {
	_, err := p.db.ExecContext(ctx, postgresSchema)
	return err
}

const accountColumns = `id, phone_e164, proxy_url, state, device_jid, auto_connect,
lease_epoch, created_at, updated_at`

type rowScanner interface {
	Scan(...any) error
}

func scanAccount(row rowScanner) (model.Account, error) {
	var account model.Account
	err := row.Scan(
		&account.ID,
		&account.PhoneE164,
		&account.ProxyURL,
		&account.State,
		&account.DeviceJID,
		&account.AutoConnect,
		&account.LeaseEpoch,
		&account.CreatedAt,
		&account.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return model.Account{}, ErrNotFound
	}
	return account, err
}

func (p *Postgres) CreateAccount(ctx context.Context, account model.Account) (model.Account, error) {
	created, err := scanAccount(p.db.QueryRowContext(ctx, `
        INSERT INTO wa_gateway.accounts (id, phone_e164, proxy_url, state, auto_connect)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING `+accountColumns,
		account.ID, account.PhoneE164, account.ProxyURL, account.State, account.AutoConnect,
	))
	if err != nil {
		var postgresError *pgconn.PgError
		if errors.As(err, &postgresError) && postgresError.Code == "23505" {
			return model.Account{}, ErrConflict
		}
	}
	return created, err
}

func (p *Postgres) ListAccounts(ctx context.Context) ([]model.Account, error) {
	rows, err := p.db.QueryContext(ctx, `SELECT `+accountColumns+` FROM wa_gateway.accounts ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	accounts := make([]model.Account, 0)
	for rows.Next() {
		account, scanErr := scanAccount(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		accounts = append(accounts, account)
	}
	return accounts, rows.Err()
}

func (p *Postgres) GetAccount(ctx context.Context, id string) (model.Account, error) {
	return scanAccount(p.db.QueryRowContext(ctx,
		`SELECT `+accountColumns+` FROM wa_gateway.accounts WHERE id=$1`, id,
	))
}

func (p *Postgres) UpdateAccount(
	ctx context.Context,
	id, phone, proxyURL string,
	autoConnect bool,
	epoch int64,
) (model.Account, error) {
	updated, err := scanAccount(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.accounts
        SET phone_e164=$2, proxy_url=$3, auto_connect=$4, updated_at=NOW()
        WHERE id=$1 AND lease_epoch = $5
        RETURNING `+accountColumns, id, phone, proxyURL, autoConnect, epoch))
	if err != nil {
		var postgresError *pgconn.PgError
		if errors.As(err, &postgresError) && postgresError.Code == "23505" {
			return model.Account{}, ErrConflict
		}
	}
	return updated, err
}

func (p *Postgres) UpdateAccountPhone(ctx context.Context, id, phone string, epoch int64) (model.Account, error) {
	return scanAccount(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.accounts
        SET phone_e164=$2, updated_at=NOW()
        WHERE id=$1 AND lease_epoch = $3
        RETURNING `+accountColumns, id, phone, epoch))
}

func (p *Postgres) UpdateAccountState(
	ctx context.Context,
	id, state string,
	autoConnect bool,
	epoch int64,
) (model.Account, error) {
	return scanAccount(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.accounts
        SET state=$2, auto_connect=$3, updated_at=NOW()
        WHERE id=$1 AND lease_epoch = $4
        RETURNING `+accountColumns, id, state, autoConnect, epoch))
}

func (p *Postgres) SetAccountDevice(
	ctx context.Context,
	id, deviceJID, state string,
	autoConnect bool,
	epoch int64,
) (model.Account, error) {
	return scanAccount(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.accounts
        SET device_jid=$2, state=$3, auto_connect=$4, updated_at=NOW()
        WHERE id=$1 AND lease_epoch = $5
        RETURNING `+accountColumns, id, deviceJID, state, autoConnect, epoch))
}

func (p *Postgres) ClearAccountDevice(ctx context.Context, id string, epoch int64) (model.Account, error) {
	return scanAccount(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.accounts
        SET device_jid='', state='unpaired', auto_connect=FALSE, updated_at=NOW()
        WHERE id=$1 AND lease_epoch = $2
        RETURNING `+accountColumns, id, epoch))
}

func (p *Postgres) AdvanceAccountFence(ctx context.Context, id string, epoch int64) error {
	result, err := p.db.ExecContext(ctx, `
        UPDATE wa_gateway.accounts
        SET lease_epoch=$2, updated_at=NOW()
        WHERE id=$1 AND lease_epoch <= $2`, id, epoch)
	if err != nil {
		return err
	}
	updated, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if updated != 1 {
		return fmt.Errorf("account lease fencing rejected for account %s", id)
	}
	return nil
}

const messageColumns = `message_id, account_id, recipient_e164, provider_message_id,
status, error_code, queued_at, sent_at, delivered_at, updated_at`

func scanMessage(row rowScanner) (model.Message, error) {
	var message model.Message
	err := row.Scan(
		&message.ID,
		&message.AccountID,
		&message.RecipientE164,
		&message.ProviderMessageID,
		&message.Status,
		&message.ErrorCode,
		&message.QueuedAt,
		&message.SentAt,
		&message.DeliveredAt,
		&message.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return model.Message{}, ErrNotFound
	}
	return message, err
}

func (p *Postgres) CreateMessage(ctx context.Context, message model.Message, epoch int64) (model.Message, bool, error) {
	created, err := scanMessage(p.db.QueryRowContext(ctx, `
        INSERT INTO wa_gateway.messages
            (message_id, account_id, recipient_e164, status, queued_at)
        SELECT $1, $2, $3, $4, $5
        WHERE EXISTS (
            SELECT 1 FROM wa_gateway.accounts
            WHERE id=$2 AND lease_epoch=$6
        )
        ON CONFLICT (message_id) DO NOTHING
        RETURNING `+messageColumns,
		message.ID, message.AccountID, message.RecipientE164, message.Status, message.QueuedAt, epoch,
	))
	if err == nil {
		return created, true, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return model.Message{}, false, err
	}
	existing, err := p.GetMessage(ctx, message.ID)
	return existing, false, err
}

func (p *Postgres) GetMessage(ctx context.Context, id string) (model.Message, error) {
	return scanMessage(p.db.QueryRowContext(ctx,
		`SELECT `+messageColumns+` FROM wa_gateway.messages WHERE message_id=$1`, id,
	))
}

func (p *Postgres) MarkMessageSent(ctx context.Context, id, providerID string, epoch int64) (model.Message, error) {
	return scanMessage(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.messages
        SET provider_message_id=$2, status='sent', sent_at=NOW(), updated_at=NOW()
		WHERE message_id=$1 AND status='queued'
		  AND EXISTS (
		      SELECT 1 FROM wa_gateway.accounts
		      WHERE id=wa_gateway.messages.account_id AND lease_epoch=$3
		  )
		RETURNING `+messageColumns, id, providerID, epoch))
}

func (p *Postgres) MarkMessageDeliveredByProviderID(
	ctx context.Context,
	providerID, accountID string,
	epoch int64,
) (model.Message, bool, error) {
	message, err := scanMessage(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.messages
        SET status='delivered', delivered_at=COALESCE(delivered_at, NOW()), updated_at=NOW()
		WHERE provider_message_id=$1 AND account_id=$2 AND status='sent'
		  AND EXISTS (
		      SELECT 1 FROM wa_gateway.accounts
		      WHERE id=$2 AND lease_epoch=$3
		  )
		RETURNING `+messageColumns, providerID, accountID, epoch))
	if errors.Is(err, ErrNotFound) {
		return model.Message{}, false, nil
	}
	return message, err == nil, err
}

func (p *Postgres) MarkMessageFailed(ctx context.Context, id, errorCode string, epoch int64) (model.Message, error) {
	return scanMessage(p.db.QueryRowContext(ctx, `
        UPDATE wa_gateway.messages
        SET status='failed', error_code=$2, updated_at=NOW()
		WHERE message_id=$1 AND status='queued'
		  AND EXISTS (
		      SELECT 1 FROM wa_gateway.accounts
		      WHERE id=wa_gateway.messages.account_id AND lease_epoch=$3
		  )
		RETURNING `+messageColumns, id, errorCode, epoch))
}
