package webhook

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
)

type Client struct {
	url        string
	secret     []byte
	httpClient *http.Client
	maxRetries int
}

func New(url, secret string, maxRetries int) *Client {
	if maxRetries < 0 {
		maxRetries = 0
	}
	return &Client{
		url:        url,
		secret:     []byte(secret),
		httpClient: &http.Client{Timeout: 8 * time.Second},
		maxRetries: maxRetries,
	}
}

func (c *Client) Enabled() bool { return c.url != "" }

func (c *Client) Deliver(ctx context.Context, message model.Message) error {
	if !c.Enabled() {
		return nil
	}
	payload := map[string]any{
		"event":     "message.status",
		"messageId": message.ID,
		"accountId": message.AccountID,
		"status":    message.Status,
		"timestamp": message.UpdatedAt,
	}
	if message.ProviderMessageID != "" {
		payload["providerMessageId"] = message.ProviderMessageID
	}
	if message.ErrorCode != "" {
		payload["errorCode"] = message.ErrorCode
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	signature := Sign(c.secret, body)
	var lastError error
	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		if attempt > 0 {
			timer := time.NewTimer(time.Duration(1<<min(attempt-1, 4)) * 250 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			case <-timer.C:
			}
		}
		request, requestErr := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))
		if requestErr != nil {
			return requestErr
		}
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("X-Parloq-Signature", "sha256="+signature)
		request.Header.Set("X-Parloq-Message-Id", message.ID)
		response, requestErr := c.httpClient.Do(request)
		if requestErr != nil {
			lastError = requestErr
			continue
		}
		_, _ = io.Copy(io.Discard, response.Body)
		_ = response.Body.Close()
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			return nil
		}
		lastError = fmt.Errorf("webhook returned HTTP %d", response.StatusCode)
		if response.StatusCode >= 400 && response.StatusCode < 500 && response.StatusCode != http.StatusTooManyRequests {
			break
		}
	}
	return lastError
}

func Sign(secret, body []byte) string {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write(body)
	return hex.EncodeToString(mac.Sum(nil))
}
