from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MfaSecurityEvent
from app.security import secret_fingerprint, utcnow


TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_ISSUER = "Parloq"
RECOVERY_CODE_COUNT = 10


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def totp_counter(at: datetime | None = None) -> int:
    moment = at or utcnow()
    return int(moment.timestamp()) // TOTP_PERIOD_SECONDS


def totp_code(secret: str, *, counter: int | None = None, at: datetime | None = None) -> str:
    value = totp_counter(at) if counter is None else counter
    digest = hmac.new(
        _secret_bytes(secret), struct.pack(">Q", value), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    *,
    last_used_counter: int | None = None,
    at: datetime | None = None,
) -> int | None:
    normalized = code.strip().replace(" ", "")
    if not re.fullmatch(r"\d{6}", normalized):
        return None
    current = totp_counter(at)
    for candidate in (current, current - 1, current + 1):
        if last_used_counter is not None and candidate <= last_used_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter=candidate), normalized):
            return candidate
    return None


def otpauth_uri(secret: str, username: str) -> str:
    label = quote(f"{TOTP_ISSUER}:{username}", safe="")
    issuer = quote(TOTP_ISSUER, safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD_SECONDS}"
    )


def generate_recovery_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(10).upper()
        codes.append("-".join(raw[index : index + 5] for index in range(0, 20, 5)))
    return codes


def _normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def recovery_code_hash(code: str) -> str:
    normalized = _normalize_recovery_code(code)
    return hmac.new(
        get_settings().app_secret_key.encode("utf-8"),
        f"mfa-recovery:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def recovery_code_hashes(codes: list[str]) -> list[str]:
    return [recovery_code_hash(code) for code in codes]


def consume_recovery_code(stored_hashes: list[str], code: str) -> tuple[bool, list[str]]:
    normalized = _normalize_recovery_code(code)
    if len(normalized) != 20:
        return False, stored_hashes
    candidate = recovery_code_hash(normalized)
    for index, stored in enumerate(stored_hashes):
        if hmac.compare_digest(candidate, stored):
            return True, [value for offset, value in enumerate(stored_hashes) if offset != index]
    return False, stored_hashes


def source_ip_hash(source_ip: str) -> str:
    return secret_fingerprint(f"mfa-source:{source_ip}")


def record_event(
    db: Session,
    event_type: str,
    *,
    user_id: int | None,
    actor_user_id: int | None = None,
    source_ip: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        MfaSecurityEvent(
            user_id=user_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            source_ip_hash=source_ip_hash(source_ip) if source_ip else None,
            details_json=details or {},
        )
    )
