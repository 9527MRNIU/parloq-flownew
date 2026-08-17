from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password cannot be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return "scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_value, expected_value = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _legacy_fernet() -> Fernet:
    secret = get_settings().app_secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _configured_fernets() -> dict[str, Fernet]:
    return {
        key_id: Fernet(key_value.encode("ascii"))
        for key_id, key_value in get_settings().data_encryption_keys
    }


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("secret cannot be empty")
    settings = get_settings()
    if settings.data_encryption_active_key_id:
        fernet = _configured_fernets().get(settings.data_encryption_active_key_id)
        if fernet is None:
            raise RuntimeError("active data encryption key is not configured")
        token = fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"v2:{settings.data_encryption_active_key_id}:{token}"
    return "v1:" + _legacy_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(payload: str) -> str:
    if payload.startswith("v2:"):
        try:
            _, key_id, token = payload.split(":", 2)
            fernet = _configured_fernets()[key_id]
            return fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, KeyError, ValueError) as exc:
            raise ValueError("secret cannot be decrypted") from exc
    if payload.startswith("v1:"):
        token = payload[3:].encode("ascii")
        candidates = [_legacy_fernet(), *_configured_fernets().values()]
        for fernet in candidates:
            try:
                return fernet.decrypt(token).decode("utf-8")
            except InvalidToken:
                continue
        raise ValueError("secret cannot be decrypted")
    raise ValueError("unsupported encrypted secret format")


def secret_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_session_token() -> tuple[str, str, datetime]:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    expires_at = utcnow() + timedelta(hours=settings.auth_session_hours)
    return token, secret_fingerprint(token), expires_at
