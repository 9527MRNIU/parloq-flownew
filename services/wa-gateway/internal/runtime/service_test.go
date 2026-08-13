package runtime

import (
	"testing"

	"github.com/parloq/parloq-flow/services/wa-gateway/internal/account"
	"github.com/parloq/parloq-flow/services/wa-gateway/internal/model"
)

func TestMaskProxyRemovesCredentials(t *testing.T) {
	masked := maskProxy("socks5://customer:super-secret@proxy.example:1080")
	if masked != "socks5://proxy.example:1080" {
		t.Fatalf("masked proxy = %q", masked)
	}
}

func TestProxyChangeRequiresDisconnectOnlyForActiveAccount(t *testing.T) {
	offline := model.Account{State: string(account.StateLinkedOffline)}
	if configurationChangeRequiresDisconnect(offline, false, false, true) {
		t.Fatal("offline account should allow proxy change")
	}
	online := model.Account{State: string(account.StateOnlineIdle)}
	if !configurationChangeRequiresDisconnect(online, true, false, true) {
		t.Fatal("online account must reject proxy change")
	}
	if configurationChangeRequiresDisconnect(online, true, false, false) {
		t.Fatal("autoConnect-only change must not require disconnect")
	}
}

func TestNormalizeE164(t *testing.T) {
	got, err := normalizeE164("+14155550123")
	if err != nil {
		t.Fatal(err)
	}
	if got != "+14155550123" {
		t.Fatalf("phone = %q", got)
	}
	if _, err = normalizeE164("+1 415 555 0123"); err == nil {
		t.Fatal("formatted phone with spaces must be rejected")
	}
}
