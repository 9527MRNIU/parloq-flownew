package lease

import (
	"testing"
	"time"
)

func TestValidateTiming(t *testing.T) {
	if err := ValidateTiming(30*time.Second, 10*time.Second); err != nil {
		t.Fatal(err)
	}
	if err := ValidateTiming(10*time.Second, 10*time.Second); err == nil {
		t.Fatal("renew interval equal to TTL must fail")
	}
}
