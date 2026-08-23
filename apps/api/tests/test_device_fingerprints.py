from __future__ import annotations

from app.services import device_fingerprints
from app.services.device_fingerprints import (
    FINGERPRINT_VERSION,
    fingerprint_identity,
    fingerprint_metadata,
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


def test_device_tokens_are_not_part_of_the_fingerprint_service() -> None:
    assert not hasattr(device_fingerprints, "issue_device_token")
    assert not hasattr(device_fingerprints, "verify_device_token")
