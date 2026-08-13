package store

import (
	"strings"
	"testing"
)

func TestNormalizePostgresURL(t *testing.T) {
	got, err := NormalizePostgresURL("postgresql+psycopg://user:pass@postgres:5432/db")
	if err != nil {
		t.Fatal(err)
	}
	if got != "postgresql://user:pass@postgres:5432/db" {
		t.Fatalf("URL = %q", got)
	}
}

func TestSchemaPersistsProxyAndFence(t *testing.T) {
	for _, column := range []string{"proxy_url", "lease_epoch", "device_jid"} {
		if !strings.Contains(postgresSchema, column) {
			t.Fatalf("gateway schema is missing %s", column)
		}
	}
}
