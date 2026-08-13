package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	enginecontract "github.com/parloq/parloq-flow/services/wa-gateway/internal/engine"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/engine/mock"
	whatsmeowengine "github.com/parloq/parloq-flow/services/wa-gateway/internal/engine/whatsmeow"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/httpserver"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/lease"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/metrics"
	gatewayruntime "github.com/parloq/parloq-flow/services/wa-gateway/internal/runtime"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/store"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/webhook"
)

const defaultShutdownTimeout = 10 * time.Second

type config struct {
	address            string
	engineName         string
	instanceID         string
	databaseURL        string
	redisURL           string
	apiToken           string
	webhookURL         string
	webhookSecret      string
	webhookRetries     int
	databaseMaxConns   int
	leaseTTL           time.Duration
	leaseRenewInterval time.Duration
	shutdownTimeout    time.Duration
	sendQPS            int
	queueSize          int
	concurrentSends    int
	restoreConcurrency int
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		url := "http://127.0.0.1:8010/healthz"
		if len(os.Args) > 2 {
			url = os.Args[2]
		}
		if err := runHealthcheck(url); err != nil {
			_, _ = fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	if err := run(logger); err != nil {
		logger.Error("gateway_stopped", "error", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	settings, err := loadConfig()
	if err != nil {
		return err
	}
	repository, err := store.NewPostgres(settings.databaseURL, settings.databaseMaxConns)
	if err != nil {
		return fmt.Errorf("open gateway database: %w", err)
	}
	defer repository.Close()
	leaseManager, err := lease.NewRedisManager(settings.redisURL, settings.instanceID, settings.leaseTTL)
	if err != nil {
		return err
	}
	defer leaseManager.Close()
	protocol, err := selectEngine(settings.engineName, repository)
	if err != nil {
		return err
	}
	metricRegistry := &metrics.Registry{}
	webhookClient := webhook.New(settings.webhookURL, settings.webhookSecret, settings.webhookRetries)
	service := gatewayruntime.New(
		repository,
		leaseManager,
		protocol,
		webhookClient,
		metricRegistry,
		logger,
		gatewayruntime.Config{
			LeaseRenewInterval: settings.leaseRenewInterval,
			SendQPS:            settings.sendQPS,
			QueueSize:          settings.queueSize,
			ConcurrentSends:    settings.concurrentSends,
			RestoreConcurrency: settings.restoreConcurrency,
		},
	)

	rootContext, stopSignals := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stopSignals()
	startupContext, cancelStartup := context.WithTimeout(rootContext, 30*time.Second)
	err = service.Start(startupContext)
	cancelStartup()
	if err != nil {
		return fmt.Errorf("start gateway runtime: %w", err)
	}

	server := httpserver.New(
		settings.address,
		settings.instanceID,
		service,
		metricRegistry,
		settings.apiToken,
		logger,
	)
	serveError := make(chan error, 1)
	go func() {
		logger.Info("gateway_started",
			"address", settings.address,
			"instance_id", settings.instanceID,
			"engine", protocol.Name(),
			"send_qps_per_account", settings.sendQPS,
			"concurrent_sends", settings.concurrentSends,
		)
		serveError <- server.ListenAndServe()
	}()

	select {
	case <-rootContext.Done():
		logger.Info("gateway_shutdown_requested")
	case err = <-serveError:
		if !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("serve gateway: %w", err)
		}
	}

	shutdownContext, cancelShutdown := context.WithTimeout(context.Background(), settings.shutdownTimeout)
	defer cancelShutdown()
	serverError := server.Shutdown(shutdownContext)
	runtimeError := service.Close(shutdownContext)
	return errors.Join(serverError, runtimeError)
}

func selectEngine(name string, repository *store.Postgres) (enginecontract.Engine, error) {
	switch name {
	case "mock":
		return mock.New(), nil
	case "whatsmeow":
		return whatsmeowengine.NewWithDB(repository.DB()), nil
	default:
		return nil, fmt.Errorf("unsupported WA_ENGINE %q", name)
	}
}

func loadConfig() (config, error) {
	databaseURL := valueOrDefault("WA_GATEWAY_DATABASE_URL", os.Getenv("DATABASE_URL"))
	if strings.TrimSpace(databaseURL) == "" {
		return config{}, errors.New("WA_GATEWAY_DATABASE_URL or DATABASE_URL is required")
	}
	redisURL := valueOrDefault("WA_GATEWAY_REDIS_URL", os.Getenv("REDIS_URL"))
	if strings.TrimSpace(redisURL) == "" {
		return config{}, errors.New("WA_GATEWAY_REDIS_URL or REDIS_URL is required")
	}
	leaseTTL, err := durationEnv("WA_GATEWAY_LEASE_TTL", 30*time.Second)
	if err != nil {
		return config{}, err
	}
	leaseRenewInterval, err := durationEnv("WA_GATEWAY_LEASE_RENEW_INTERVAL", 10*time.Second)
	if err != nil {
		return config{}, err
	}
	if err = lease.ValidateTiming(leaseTTL, leaseRenewInterval); err != nil {
		return config{}, err
	}
	shutdownTimeout, err := durationEnv("WA_GATEWAY_SHUTDOWN_TIMEOUT", defaultShutdownTimeout)
	if err != nil {
		return config{}, err
	}
	sendQPS, err := intEnv("WA_GATEWAY_SEND_QPS", 10, 1, 10)
	if err != nil {
		return config{}, err
	}
	queueSize, err := intEnv("WA_GATEWAY_ACCOUNT_QUEUE_SIZE", 1000, 10, 100000)
	if err != nil {
		return config{}, err
	}
	concurrentSends, err := intEnv("WA_GATEWAY_CONCURRENT_SENDS", 200, 1, 10000)
	if err != nil {
		return config{}, err
	}
	restoreConcurrency, err := intEnv("WA_GATEWAY_RESTORE_CONCURRENCY", 25, 1, 500)
	if err != nil {
		return config{}, err
	}
	databaseMaxConns, err := intEnv("WA_GATEWAY_DATABASE_MAX_CONNECTIONS", 50, 2, 500)
	if err != nil {
		return config{}, err
	}
	webhookRetries, err := intEnv("WA_GATEWAY_WEBHOOK_RETRIES", 3, 0, 10)
	if err != nil {
		return config{}, err
	}
	webhookURL := strings.TrimSpace(os.Getenv("WA_GATEWAY_WEBHOOK_URL"))
	webhookSecret := strings.TrimSpace(os.Getenv("WA_GATEWAY_WEBHOOK_SECRET"))
	if webhookURL != "" && len(webhookSecret) < 16 {
		return config{}, errors.New("WA_GATEWAY_WEBHOOK_SECRET must contain at least 16 characters when webhook is enabled")
	}
	engineName := valueOrDefault("WA_ENGINE", "mock")
	apiToken := strings.TrimSpace(os.Getenv("WA_GATEWAY_API_TOKEN"))
	if engineName == "whatsmeow" && len(apiToken) < 32 {
		return config{}, errors.New("WA_GATEWAY_API_TOKEN must contain at least 32 characters with WA_ENGINE=whatsmeow")
	}
	return config{
		address:            valueOrDefault("WA_GATEWAY_ADDR", ":8010"),
		engineName:         engineName,
		instanceID:         valueOrDefault("WA_GATEWAY_INSTANCE_ID", "local-wa-gateway-1"),
		databaseURL:        databaseURL,
		redisURL:           redisURL,
		apiToken:           apiToken,
		webhookURL:         webhookURL,
		webhookSecret:      webhookSecret,
		webhookRetries:     webhookRetries,
		databaseMaxConns:   databaseMaxConns,
		leaseTTL:           leaseTTL,
		leaseRenewInterval: leaseRenewInterval,
		shutdownTimeout:    shutdownTimeout,
		sendQPS:            sendQPS,
		queueSize:          queueSize,
		concurrentSends:    concurrentSends,
		restoreConcurrency: restoreConcurrency,
	}, nil
}

func valueOrDefault(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func durationEnv(name string, fallback time.Duration) (time.Duration, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	parsed, err := time.ParseDuration(raw)
	if err != nil || parsed <= 0 {
		return 0, fmt.Errorf("invalid %s %q", name, raw)
	}
	return parsed, nil
}

func intEnv(name string, fallback, minimum, maximum int) (int, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed < minimum || parsed > maximum {
		return 0, fmt.Errorf("%s must be between %d and %d", name, minimum, maximum)
	}
	return parsed, nil
}

func runHealthcheck(url string) error {
	client := &http.Client{Timeout: 3 * time.Second}
	response, err := client.Get(url)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("healthcheck returned HTTP %d", response.StatusCode)
	}
	return nil
}
