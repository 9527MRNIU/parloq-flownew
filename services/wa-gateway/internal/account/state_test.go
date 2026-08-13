package account

import "testing"

func TestCampaignLifecycle(t *testing.T) {
	states := []State{
		StateLinkedOffline,
		StateWarming,
		StateOnlineIdle,
		StateSending,
		StateDraining,
		StateLinkedOffline,
	}
	for index := 0; index < len(states)-1; index++ {
		if err := ValidateTransition(states[index], states[index+1]); err != nil {
			t.Fatalf("expected transition to be valid: %v", err)
		}
	}
}

func TestSendingCannotTransitionDirectlyToDisabled(t *testing.T) {
	if err := ValidateTransition(StateSending, StateDisabled); err == nil {
		t.Fatal("expected sending -> disabled to be rejected until work is stopped")
	}
}

func TestUnknownStateIsInvalid(t *testing.T) {
	if State("unknown").Valid() {
		t.Fatal("unknown state must not be valid")
	}
}
