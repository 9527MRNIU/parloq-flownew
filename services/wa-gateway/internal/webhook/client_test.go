package webhook

import "testing"

func TestSignIsStable(t *testing.T) {
	got := Sign([]byte("secret"), []byte(`{"messageId":"msg-1"}`))
	want := "07cbfa6121f0d4e10a59a2f4be4f38ad6b99c2865001f1f1a53c83f6f45b451f"
	if got != want {
		t.Fatalf("signature = %q, want %q", got, want)
	}
}
