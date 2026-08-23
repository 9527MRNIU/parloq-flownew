from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

from app.config import get_settings
from app.security import utcnow


TOKEN_PREFIX = "df1"
TOKEN_TTL_SECONDS = 1_800
FINGERPRINT_VERSION = "thumbmarkjs/1.10.1"


@dataclass(frozen=True, slots=True)
class DeviceFingerprintIdentity:
    fingerprint_hash: str
    limit_keys: tuple[str, ...]
    quality: str
    version: str
    profile: str
    component_mask: tuple[str, ...]


def _hmac_hex(purpose: str, value: str) -> str:
    return hmac.new(
        get_settings().app_secret_key.encode(),
        f"{purpose}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def fingerprint_identity(
    tenant_id: int,
    raw_fingerprint: str | None,
) -> DeviceFingerprintIdentity | None:
    if raw_fingerprint is None:
        return None
    fallback = raw_fingerprint.startswith("fb_")
    fingerprint_hash = _hmac_hex(
        "visitor-fingerprint:v2",
        f"tenant:{tenant_id}|raw:{raw_fingerprint}",
    )
    return DeviceFingerprintIdentity(
        fingerprint_hash=fingerprint_hash,
        limit_keys=(fingerprint_hash,),
        quality="low" if fallback else "high",
        version=FINGERPRINT_VERSION,
        profile="fallback" if fallback else "thumbmarkjs",
        component_mask=(),
    )


def fingerprint_metadata(
    identity: DeviceFingerprintIdentity | None,
) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "version": identity.version,
        "profile": identity.profile,
        "quality": identity.quality,
    }


def issue_device_token(
    identity: DeviceFingerprintIdentity,
    *,
    channel_id: str,
    tenant_id: int,
    visitor_id: str,
) -> str:
    issued_at = int(utcnow().timestamp())
    payload = {
        "channel": channel_id,
        "tenant": str(tenant_id),
        "visitor": visitor_id,
        "fingerprint": identity.fingerprint_hash,
        "limitKeys": list(identity.limit_keys),
        "quality": identity.quality,
        "fingerprintVersion": identity.version,
        "profile": identity.profile,
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL_SECONDS,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = _hmac_hex("visitor-device-token:v1", encoded)
    return f"{TOKEN_PREFIX}.{encoded}.{signature}"


def verify_device_token(
    token: str,
    *,
    channel_id: str,
    tenant_id: int,
    visitor_id: str,
) -> DeviceFingerprintIdentity:
    try:
        prefix, encoded, signature = token.split(".", 2)
        expected = _hmac_hex("visitor-device-token:v1", encoded)
        if prefix != TOKEN_PREFIX or not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        limit_keys = payload.get("limitKeys")
        if (
            payload.get("channel") != channel_id
            or payload.get("tenant") != str(tenant_id)
            or payload.get("visitor") != visitor_id
            or int(payload.get("exp", 0)) < int(utcnow().timestamp())
            or payload.get("quality") not in {"high", "medium", "low"}
            or not isinstance(limit_keys, list)
            or len(limit_keys) > 12
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in limit_keys
            )
        ):
            raise ValueError
        fingerprint_hash = payload.get("fingerprint")
        if (
            not isinstance(fingerprint_hash, str)
            or len(fingerprint_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in fingerprint_hash
            )
        ):
            raise ValueError
        return DeviceFingerprintIdentity(
            fingerprint_hash=fingerprint_hash,
            limit_keys=tuple(dict.fromkeys(limit_keys)),
            quality=payload["quality"],
            version=str(payload.get("fingerprintVersion") or ""),
            profile=str(payload.get("profile") or "other"),
            component_mask=(),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("invalid device token") from None
