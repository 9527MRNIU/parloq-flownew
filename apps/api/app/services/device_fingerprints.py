from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
from itertools import combinations
import json
from typing import Any

from app.business_schemas import PromotionDeviceFingerprint
from app.config import get_settings
from app.security import utcnow


TOKEN_PREFIX = "df1"
TOKEN_TTL_SECONDS = 1_800
STABLE_COMPONENTS_BY_PROFILE: dict[str, tuple[str, ...]] = {
    "chromium": (
        "canvas",
        "audio",
        "fonts",
        "webgl",
        "hardware",
        "math",
        "system",
    ),
    # Brave deliberately randomizes some render/audio surfaces. Excluding
    # those values is more stable than folding every available signal into a
    # single exact hash.
    "brave": ("fonts", "webgl", "hardware", "math", "system"),
    "firefox": ("audio", "fonts", "webgl", "hardware", "math", "system"),
    "safari": ("audio", "fonts", "webgl", "hardware", "math", "system"),
    "other": (
        "canvas",
        "audio",
        "fonts",
        "webgl",
        "hardware",
        "math",
        "system",
    ),
}


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


def _component_values(
    payload: PromotionDeviceFingerprint,
) -> dict[str, str]:
    return {
        key: value
        for key, value in payload.components.model_dump().items()
        if isinstance(value, str)
    }


def fingerprint_identity(
    tenant_id: int,
    payload: PromotionDeviceFingerprint | None,
) -> DeviceFingerprintIdentity | None:
    if payload is None:
        return None
    supplied = _component_values(payload)
    stable_names = STABLE_COMPONENTS_BY_PROFILE[payload.profile]
    stable = [(name, supplied[name]) for name in stable_names if name in supplied]
    if not stable:
        return None

    canonical = "|".join(f"{name}={value}" for name, value in stable)
    fingerprint_hash = _hmac_hex(
        "visitor-fingerprint:v1",
        f"tenant:{tenant_id}|profile:{payload.profile}|{canonical}",
    )
    quality = "high" if len(stable) >= 4 else "medium" if len(stable) >= 3 else "low"

    # Triple-component match keys let one unstable component drift without
    # losing an otherwise strong device match. They contain only tenant-scoped
    # server HMAC values, never the browser's component hashes.
    limit_keys: list[str] = [fingerprint_hash]
    if quality in {"high", "medium"}:
        candidates = stable[:5]
        for group in combinations(candidates, 3):
            material = "|".join(f"{name}={value}" for name, value in group)
            limit_keys.append(
                _hmac_hex(
                    "visitor-fingerprint-match:v1",
                    f"tenant:{tenant_id}|{material}",
                )
            )
    return DeviceFingerprintIdentity(
        fingerprint_hash=fingerprint_hash,
        limit_keys=tuple(dict.fromkeys(limit_keys if quality != "low" else ())),
        quality=quality,
        version=payload.version,
        profile=payload.profile,
        component_mask=tuple(name for name, _value in stable),
    )


def fingerprint_metadata(
    identity: DeviceFingerprintIdentity | None,
    payload: PromotionDeviceFingerprint | None,
) -> dict[str, Any] | None:
    if identity is None or payload is None:
        return None
    return {
        "version": identity.version,
        "profile": identity.profile,
        "quality": identity.quality,
        "componentMask": list(identity.component_mask),
        "availability": payload.availability,
        "elapsedMs": payload.elapsed_ms,
    }


def issue_device_token(
    identity: DeviceFingerprintIdentity,
    *,
    channel_id: str,
    tenant_id: int,
    visitor_id: str,
    session_nonce: str,
    session_expires_at: int,
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
        "sessionNonce": session_nonce,
        "iat": issued_at,
        "exp": min(issued_at + TOKEN_TTL_SECONDS, session_expires_at),
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
    session_nonce: str,
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
            or payload.get("sessionNonce") != session_nonce
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
