package httpserver

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/metrics"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
	gatewayruntime "github.com/parloq/parloq-flow/services/wa-gateway/internal/runtime"
)

type testController struct {
	readyError     error
	updatedAccount model.Account
}

func (c testController) Ready(context.Context) error { return c.readyError }
func (testController) EngineName() string            { return "mock" }
func (testController) CreateAccount(context.Context, gatewayruntime.CreateAccountRequest) (model.Account, error) {
	return model.Account{}, errors.New("unused")
}
func (testController) ListAccounts(context.Context) ([]model.Account, error) {
	return nil, errors.New("unused")
}
func (testController) GetAccount(context.Context, string) (model.Account, error) {
	return model.Account{}, errors.New("unused")
}
func (c testController) UpdateAccount(context.Context, string, gatewayruntime.UpdateAccountRequest) (model.Account, error) {
	if c.updatedAccount.ID != "" {
		return c.updatedAccount, nil
	}
	return model.Account{}, errors.New("unused")
}
func (testController) RequestPairingCode(context.Context, string, gatewayruntime.PairingCodeRequest) (engine.PairResult, error) {
	return engine.PairResult{}, errors.New("unused")
}
func (testController) Connect(context.Context, string) (model.Account, error) {
	return model.Account{}, errors.New("unused")
}
func (testController) Disconnect(context.Context, string) (model.Account, error) {
	return model.Account{}, errors.New("unused")
}
func (testController) Logout(context.Context, string) (model.Account, error) {
	return model.Account{}, errors.New("unused")
}
func (testController) SendText(context.Context, string, gatewayruntime.SendTextRequest) (model.Message, error) {
	return model.Message{}, errors.New("unused")
}
func (testController) GetMessage(context.Context, string) (model.Message, error) {
	return model.Message{}, errors.New("unused")
}

func newTestServer(controller Controller, token string) *Server {
	return New(":0", "test-instance", controller, &metrics.Registry{}, token,
		slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func TestHealthAndReadiness(t *testing.T) {
	server := newTestServer(testController{}, "")
	testServer := httptest.NewServer(server.httpServer.Handler)
	defer testServer.Close()
	for _, path := range []string{"/healthz", "/readyz"} {
		response, err := http.Get(testServer.URL + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		_ = response.Body.Close()
		if response.StatusCode != http.StatusOK {
			t.Fatalf("GET %s status = %d, want 200", path, response.StatusCode)
		}
	}
}

func TestReadinessFailure(t *testing.T) {
	server := newTestServer(testController{readyError: errors.New("not ready")}, "")
	request := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	recorder := httptest.NewRecorder()
	server.httpServer.Handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", recorder.Code)
	}
}

func TestControlEndpointsRequireBearerToken(t *testing.T) {
	server := newTestServer(testController{}, "test-token")
	request := httptest.NewRequest(http.MethodGet, "/v1/accounts", nil)
	recorder := httptest.NewRecorder()
	server.httpServer.Handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", recorder.Code)
	}
}

func TestPatchAccountReturnsUpdatedProxy(t *testing.T) {
	server := newTestServer(testController{updatedAccount: model.Account{
		ID:          "wa_test",
		ProxyMasked: "socks5://proxy.example:1080",
		State:       "linked_offline",
	}}, "test-token")
	request := httptest.NewRequest(http.MethodPatch, "/v1/accounts/wa_test",
		bytes.NewBufferString(`{"proxyUrl":"socks5://user:pass@proxy.example:1080"}`))
	request.Header.Set("Authorization", "Bearer test-token")
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	server.httpServer.Handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if bytes.Contains(recorder.Body.Bytes(), []byte("pass")) {
		t.Fatal("response leaked proxy password")
	}
}
