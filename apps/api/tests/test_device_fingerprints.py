from __future__ import annotations

import pytest

from app.business_schemas import PromotionDeviceFingerprint
from app.services.device_fingerprints import (
    fingerprint_identity,
    issue_device_token,
    verify_device_token,
)


def _payload(
    *,
    profile: str = "chromium",
    overrides: dict[str, str] | None = None,
) -> PromotionDeviceFingerprint:
    components = {
        "canvas": "1" * 64,
        "audio": "2" * 64,
        "fonts": "3" * 64,
        "webgl": "4" * 64,
        "hardware": "5" * 64,
        "math": "6" * 64,
        "system": "7" * 64,
        **(overrides or {}),
    }
    return PromotionDeviceFingerprint.model_validate(
        {
            "version": "device-fingerprint/v1",
            "profile": profile,
            "components": components,
            "availability": {key: "ok" for key in components},
            "elapsedMs": 125,
        }
    )


def test_fingerprint_is_tenant_scoped_and_stabilized() -> None:
    original = fingerprint_identity(1001, _payload())
    repeated = fingerprint_identity(1001, _payload())
    other_tenant = fingerprint_identity(1002, _payload())
    assert original is not None
    assert repeated is not None
    assert other_tenant is not None
    assert original.fingerprint_hash == repeated.fingerprint_hash
    assert original.fingerprint_hash != other_tenant.fingerprint_hash
    assert original.quality == "high"
    assert len(original.limit_keys) > 1

    # Brave randomizes Canvas and audio surfaces, so its stable profile does
    # not let those values rotate the server identity.
    brave = fingerprint_identity(1001, _payload(profile="brave"))
    brave_rotated = fingerprint_identity(
        1001,
        _payload(
            profile="brave",
            overrides={"canvas": "8" * 64, "audio": "9" * 64},
        ),
    )
    assert brave is not None
    assert brave_rotated is not None
    assert brave.fingerprint_hash == brave_rotated.fingerprint_hash


def test_fingerprint_match_keys_survive_one_component_drift() -> None:
    original = fingerprint_identity(2001, _payload())
    canvas_changed = fingerprint_identity(
        2001, _payload(overrides={"canvas": "a" * 64})
    )
    assert original is not None
    assert canvas_changed is not None
    assert original.fingerprint_hash != canvas_changed.fingerprint_hash
    assert set(original.limit_keys) & set(canvas_changed.limit_keys)


def test_device_token_binds_channel_tenant_visitor_and_session() -> None:
    identity = fingerprint_identity(3001, _payload())
    assert identity is not None
    token = issue_device_token(
        identity,
        channel_id="4780486454931654",
        tenant_id=3001,
        visitor_id="visitor-device-0001",
        session_nonce="session-nonce",
        session_expires_at=4_102_444_800,
    )
    verified = verify_device_token(
        token,
        channel_id="4780486454931654",
        tenant_id=3001,
        visitor_id="visitor-device-0001",
        session_nonce="session-nonce",
    )
    assert verified.fingerprint_hash == identity.fingerprint_hash
    assert verified.limit_keys == identity.limit_keys

    with pytest.raises(ValueError):
        verify_device_token(
            token,
            channel_id="4780486454931654",
            tenant_id=3001,
            visitor_id="different-visitor",
            session_nonce="session-nonce",
        )
    with pytest.raises(ValueError):
        verify_device_token(
            f"{token}x",
            channel_id="4780486454931654",
            tenant_id=3001,
            visitor_id="visitor-device-0001",
            session_nonce="session-nonce",
        )
