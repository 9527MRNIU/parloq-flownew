from __future__ import annotations

import base64
import binascii
import hashlib
from urllib.parse import urlparse

from app.models import PersonalAccount
from app.security import utcnow


MAX_ACCOUNT_AVATAR_BYTES = 2 * 1024 * 1024


def _detected_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if (
        len(content) >= 12
        and content[4:8] == b"ftyp"
        and content[8:12] in {b"avif", b"avis"}
    ):
        return "image/avif"
    return None


def _safe_source_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return value


def _clear_avatar(account: PersonalAccount) -> None:
    account.avatar_source_url = None
    account.avatar_content_type = None
    account.avatar_size = None
    account.avatar_sha256 = None
    account.avatar_content = None
    account.avatar_fetched_at = None


def apply_gateway_avatar(account: PersonalAccount, value: dict) -> bool:
    """Persist a transient gateway avatar payload without trusting its metadata."""

    if "avatar" not in value:
        return False
    avatar = value.get("avatar")
    if avatar is None:
        _clear_avatar(account)
        return True
    if not isinstance(avatar, dict):
        return False

    source_url = _safe_source_url(avatar.get("sourceUrl"))
    if source_url is None:
        return False
    account.avatar_source_url = source_url

    encoded = avatar.get("dataBase64")
    if not isinstance(encoded, str) or not encoded:
        # Keep the previous downloaded image if WhatsApp returned a fresh URL
        # but its CDN download failed during this synchronization attempt.
        return True
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return False
    if not content or len(content) > MAX_ACCOUNT_AVATAR_BYTES:
        return False

    content_type = _detected_content_type(content)
    declared_type = avatar.get("contentType")
    if content_type is None or declared_type != content_type:
        return False
    declared_size = avatar.get("size")
    if (
        not isinstance(declared_size, int)
        or isinstance(declared_size, bool)
        or declared_size != len(content)
    ):
        return False
    digest = hashlib.sha256(content).hexdigest()
    if avatar.get("sha256") != digest:
        return False

    account.avatar_content_type = content_type
    account.avatar_size = len(content)
    account.avatar_sha256 = digest
    account.avatar_content = content
    account.avatar_fetched_at = utcnow()
    return True
