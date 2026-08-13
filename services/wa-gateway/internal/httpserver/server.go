// Package httpserver exposes health probes and the gateway control API.
package httpserver

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/lease"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/metrics"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
	gatewayruntime "github.com/parloq/parloq-flow/services/wa-gateway/internal/runtime"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/store"
)

type Controller interface {
	Ready(context.Context) error
	EngineName() string
	CreateAccount(context.Context, gatewayruntime.CreateAccountRequest) (model.Account, error)
	ListAccounts(context.Context) ([]model.Account, error)
	GetAccount(context.Context, string) (model.Account, error)
	UpdateAccount(context.Context, string, gatewayruntime.UpdateAccountRequest) (model.Account, error)
	RequestPairingCode(context.Context, string, gatewayruntime.PairingCodeRequest) (engine.PairResult, error)
	Connect(context.Context, string) (model.Account, error)
	Disconnect(context.Context, string) (model.Account, error)
	Logout(context.Context, string) (model.Account, error)
	SendText(context.Context, string, gatewayruntime.SendTextRequest) (model.Message, error)
	GetMessage(context.Context, string) (model.Message, error)
}

type Server struct {
	httpServer *http.Server
	controller Controller
	metrics    *metrics.Registry
	apiToken   string
	logger     *slog.Logger
}

func New(
	address, instanceID string,
	controller Controller,
	metricRegistry *metrics.Registry,
	apiToken string,
	logger *slog.Logger,
) *Server {
	server := &Server{
		controller: controller,
		metrics:    metricRegistry,
		apiToken:   apiToken,
		logger:     logger,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]any{
			"status":      "ok",
			"service":     "wa-gateway",
			"instance_id": instanceID,
			"engine":      controller.EngineName(),
		})
	})
	mux.HandleFunc("GET /readyz", server.ready)
	mux.Handle("GET /metrics", server.authorize(http.HandlerFunc(server.prometheusMetrics)))
	mux.Handle("POST /v1/accounts", server.authorize(http.HandlerFunc(server.createAccount)))
	mux.Handle("GET /v1/accounts", server.authorize(http.HandlerFunc(server.listAccounts)))
	mux.Handle("GET /v1/accounts/{accountID}", server.authorize(http.HandlerFunc(server.getAccount)))
	mux.Handle("PATCH /v1/accounts/{accountID}", server.authorize(http.HandlerFunc(server.updateAccount)))
	mux.Handle("POST /v1/accounts/{accountID}/pairing-code", server.authorize(http.HandlerFunc(server.requestPairingCode)))
	mux.Handle("POST /v1/accounts/{accountID}/connect", server.authorize(http.HandlerFunc(server.connect)))
	mux.Handle("POST /v1/accounts/{accountID}/disconnect", server.authorize(http.HandlerFunc(server.disconnect)))
	mux.Handle("POST /v1/accounts/{accountID}/logout", server.authorize(http.HandlerFunc(server.logout)))
	mux.Handle("POST /v1/accounts/{accountID}/messages", server.authorize(http.HandlerFunc(server.sendText)))
	mux.Handle("GET /v1/messages/{messageID}", server.authorize(http.HandlerFunc(server.getMessage)))

	server.httpServer = &http.Server{
		Addr:              address,
		Handler:           accessLog(mux, logger),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	return server
}

func (s *Server) ListenAndServe() error              { return s.httpServer.ListenAndServe() }
func (s *Server) Shutdown(ctx context.Context) error { return s.httpServer.Shutdown(ctx) }

func (s *Server) ready(writer http.ResponseWriter, request *http.Request) {
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	if err := s.controller.Ready(ctx); err != nil {
		writeJSON(writer, http.StatusServiceUnavailable, map[string]any{
			"status": "not_ready",
			"engine": s.controller.EngineName(),
		})
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"status": "ready",
		"engine": s.controller.EngineName(),
	})
}

func (s *Server) createAccount(writer http.ResponseWriter, request *http.Request) {
	var payload gatewayruntime.CreateAccountRequest
	if !decodeJSON(writer, request, &payload) {
		return
	}
	created, err := s.controller.CreateAccount(request.Context(), payload)
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusCreated, map[string]any{"data": created})
}

func (s *Server) listAccounts(writer http.ResponseWriter, request *http.Request) {
	accounts, err := s.controller.ListAccounts(request.Context())
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": accounts})
}

func (s *Server) getAccount(writer http.ResponseWriter, request *http.Request) {
	current, err := s.controller.GetAccount(request.Context(), request.PathValue("accountID"))
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": current})
}

func (s *Server) updateAccount(writer http.ResponseWriter, request *http.Request) {
	var payload gatewayruntime.UpdateAccountRequest
	if !decodeJSON(writer, request, &payload) {
		return
	}
	updated, err := s.controller.UpdateAccount(request.Context(), request.PathValue("accountID"), payload)
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": updated})
}

func (s *Server) requestPairingCode(writer http.ResponseWriter, request *http.Request) {
	var payload gatewayruntime.PairingCodeRequest
	if !decodeJSON(writer, request, &payload) {
		return
	}
	result, err := s.controller.RequestPairingCode(request.Context(), request.PathValue("accountID"), payload)
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": result})
}

func (s *Server) connect(writer http.ResponseWriter, request *http.Request) {
	current, err := s.controller.Connect(request.Context(), request.PathValue("accountID"))
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": current})
}

func (s *Server) disconnect(writer http.ResponseWriter, request *http.Request) {
	current, err := s.controller.Disconnect(request.Context(), request.PathValue("accountID"))
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"data": current,
		"meta": map[string]any{
			"sessionPreserved": true,
			"message":          "Disconnected. The saved session can reconnect without pairing again.",
		},
	})
}

func (s *Server) logout(writer http.ResponseWriter, request *http.Request) {
	current, err := s.controller.Logout(request.Context(), request.PathValue("accountID"))
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"data": current,
		"meta": map[string]any{
			"sessionPreserved": false,
			"message":          "Logged out. The linked-device session was removed and pairing is required.",
		},
	})
}

func (s *Server) sendText(writer http.ResponseWriter, request *http.Request) {
	var payload gatewayruntime.SendTextRequest
	if !decodeJSON(writer, request, &payload) {
		return
	}
	message, err := s.controller.SendText(request.Context(), request.PathValue("accountID"), payload)
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusAccepted, map[string]any{"data": message})
}

func (s *Server) getMessage(writer http.ResponseWriter, request *http.Request) {
	message, err := s.controller.GetMessage(request.Context(), request.PathValue("messageID"))
	if err != nil {
		s.writeError(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"data": message})
}

func (s *Server) prometheusMetrics(writer http.ResponseWriter, _ *http.Request) {
	writer.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	writer.WriteHeader(http.StatusOK)
	s.metrics.WritePrometheus(writer)
}

func (s *Server) authorize(next http.Handler) http.Handler {
	if s.apiToken == "" {
		return next
	}
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		provided := strings.TrimPrefix(request.Header.Get("Authorization"), "Bearer ")
		if subtle.ConstantTimeCompare([]byte(provided), []byte(s.apiToken)) != 1 {
			writeAPIError(writer, http.StatusUnauthorized, "unauthorized", "Missing or invalid gateway bearer token.")
			return
		}
		next.ServeHTTP(writer, request)
	})
}

func (s *Server) writeError(writer http.ResponseWriter, err error) {
	statusCode := http.StatusInternalServerError
	code := "internal_error"
	message := "The gateway could not complete the request."
	switch {
	case errors.Is(err, store.ErrNotFound):
		statusCode, code, message = http.StatusNotFound, "not_found", "The requested account or message does not exist."
	case errors.Is(err, gatewayruntime.ErrInvalidArgument):
		statusCode, code, message = http.StatusBadRequest, "invalid_argument", strings.TrimPrefix(err.Error(), gatewayruntime.ErrInvalidArgument.Error()+": ")
	case errors.Is(err, gatewayruntime.ErrConflict), errors.Is(err, store.ErrConflict), errors.Is(err, lease.ErrUnavailable):
		statusCode, code, message = http.StatusConflict, "conflict", strings.TrimPrefix(err.Error(), gatewayruntime.ErrConflict.Error()+": ")
	case errors.Is(err, gatewayruntime.ErrQueueFull):
		statusCode, code, message = http.StatusTooManyRequests, "queue_full", "The account send queue is full. Try again later."
	case errors.Is(err, gatewayruntime.ErrProtocol):
		statusCode, code, message = http.StatusBadGateway, "protocol_error", strings.TrimPrefix(err.Error(), gatewayruntime.ErrProtocol.Error()+": ")
	case errors.Is(err, engine.ErrAccountOffline):
		statusCode, code, message = http.StatusConflict, "account_offline", "The account is not connected."
	}
	if statusCode >= 500 {
		s.logger.Error("gateway_request_failed", "error", err)
	}
	writeAPIError(writer, statusCode, code, message)
}

func decodeJSON(writer http.ResponseWriter, request *http.Request, output any) bool {
	request.Body = http.MaxBytesReader(writer, request.Body, 1<<20)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(output); err != nil {
		writeAPIError(writer, http.StatusBadRequest, "invalid_json", fmt.Sprintf("Invalid JSON request: %v", err))
		return false
	}
	return true
}

func writeAPIError(writer http.ResponseWriter, statusCode int, code, message string) {
	writeJSON(writer, statusCode, map[string]any{
		"error": map[string]string{"code": code, "message": message},
	})
}

func accessLog(next http.Handler, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		startedAt := time.Now()
		next.ServeHTTP(writer, request)
		logger.Debug("http_request",
			"method", request.Method,
			"path", request.URL.Path,
			"duration_ms", time.Since(startedAt).Milliseconds(),
		)
	})
}

func writeJSON(writer http.ResponseWriter, statusCode int, value any) {
	writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	writer.Header().Set("Cache-Control", "no-store")
	writer.WriteHeader(statusCode)
	_ = json.NewEncoder(writer).Encode(value)
}
