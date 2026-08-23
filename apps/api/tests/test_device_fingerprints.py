from __future__ import annotations

import pytest

from app.services.device_fingerprints import (
    FINGERPRINT_VERSION,
    fingerprint_identity,
    fingerprint_metadata,
    issue_device_token,
    verify_device_token,
)


THUMBMARK = "0ef8bdbc97de077c45a46358ecc4ba42"


def test_thumbmark_is_hmac_scoped_to_the_tenant() -> None:
    original = fingerprint_identity(1001, THUMBMARK)
    repeated = fingerprint_identity(1001, THUMBMARK)
    other_tenant = fingerprint_identity(1002, THUMBMARK)

    assert original is not None
    assert repeated is not None
    assert other_tenant is not None
    assert original.fingerprint_hash == repeated.fingerprint_hash
    assert original.fingerprint_hash != other_tenant.fingerprint_hash
    assert original.fingerprint_hash != THUMBMARK
    assert len(original.fingerprint_hash) == 64
    assert original.limit_keys == (original.fingerprint_hash,)
    assert original.quality == "high"
    assert original.version == FINGERPRINT_VERSION
    assert original.profile == "thumbmarkjs"
    assert fingerprint_metadata(original) == {
        "version": "thumbmarkjs/1.10.1",
        "profile": "thumbmarkjs",
        "quality": "high",
    }


def test_peer_style_fallback_is_tenant_scoped_and_marked_low_quality() -> None:
    identity = fingerprint_identity(2001, "fb_k9x7q2m4_1787500800000")
    assert identity is not None
    assert identity.limit_keys == (identity.fingerprint_hash,)
    assert identity.quality == "low"
    assert identity.profile == "fallback"


def test_device_token_binds_channel_tenant_and_visitor() -> None:
    identity = fingerprint_identity(3001, THUMBMARK)
    assert identity is not None
    token = issue_device_token(
        identity,
        channel_id="4780486454931654",
        tenant_id=3001,
        visitor_id="visitor-device-0001",
    )
    verified = verify_device_token(
        token,
        channel_id="4780486454931654",
        tenant_id=3001,
        visitor_id="visitor-device-0001",
    )
    assert verified.fingerprint_hash == identity.fingerprint_hash
    assert verified.limit_keys == identity.limit_keys

    with pytest.raises(ValueError):
        verify_device_token(
            token,
            channel_id="4780486454931654",
            tenant_id=3001,
            visitor_id="different-visitor",
        )
    with pytest.raises(ValueError):
        verify_device_token(
            f"{token}x",
            channel_id="4780486454931654",
            tenant_id=3001,
            visitor_id="visitor-device-0001",
        )
