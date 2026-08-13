// Package account contains protocol-independent account lifecycle rules.
package account

import "fmt"

type State string

const (
	StateUnpaired       State = "unpaired"
	StatePairing        State = "pairing"
	StateLinkedOffline  State = "linked_offline"
	StateWarming        State = "warming"
	StateOnlineIdle     State = "online_idle"
	StateSending        State = "sending"
	StateDraining       State = "draining"
	StateReauthRequired State = "reauth_required"
	StateRestricted     State = "restricted"
	StateDisabled       State = "disabled"
)

var allowedTransitions = map[State]map[State]struct{}{
	StateUnpaired: {
		StatePairing:  {},
		StateDisabled: {},
	},
	StatePairing: {
		StateLinkedOffline:  {},
		StateUnpaired:       {},
		StateReauthRequired: {},
		StateRestricted:     {},
		StateDisabled:       {},
	},
	StateLinkedOffline: {
		StateWarming:        {},
		StatePairing:        {},
		StateReauthRequired: {},
		StateRestricted:     {},
		StateDisabled:       {},
	},
	StateWarming: {
		StateOnlineIdle:     {},
		StateLinkedOffline:  {},
		StateReauthRequired: {},
		StateRestricted:     {},
		StateDisabled:       {},
	},
	StateOnlineIdle: {
		StateSending:        {},
		StateLinkedOffline:  {},
		StateReauthRequired: {},
		StateRestricted:     {},
		StateDisabled:       {},
	},
	StateSending: {
		StateOnlineIdle:     {},
		StateDraining:       {},
		StateLinkedOffline:  {},
		StateReauthRequired: {},
		StateRestricted:     {},
	},
	StateDraining: {
		StateOnlineIdle:     {},
		StateLinkedOffline:  {},
		StateReauthRequired: {},
		StateRestricted:     {},
	},
	StateReauthRequired: {
		StatePairing:  {},
		StateDisabled: {},
	},
	StateRestricted: {
		StateLinkedOffline: {},
		StateDisabled:      {},
	},
	StateDisabled: {
		StateUnpaired:      {},
		StateLinkedOffline: {},
	},
}

func (s State) Valid() bool {
	_, ok := allowedTransitions[s]
	return ok
}

func CanTransition(from, to State) bool {
	if from == to {
		return from.Valid()
	}
	_, ok := allowedTransitions[from][to]
	return ok
}

func ValidateTransition(from, to State) error {
	if !CanTransition(from, to) {
		return fmt.Errorf("invalid account state transition %q -> %q", from, to)
	}
	return nil
}
