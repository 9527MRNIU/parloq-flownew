from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PromotionVisitor
from app.security import utcnow


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


def resolve_promotion_visitor(
    db: Session,
    *,
    tenant_id: int,
    raw_fingerprint: str,
) -> tuple[PromotionVisitor, DeviceFingerprintIdentity]:
    identity = fingerprint_identity(tenant_id, raw_fingerprint)
    if identity is None:
        raise ValueError("device fingerprint is required")
    now = utcnow()
    visitor = db.scalar(
        select(PromotionVisitor).where(
            PromotionVisitor.tenant_id == tenant_id,
            PromotionVisitor.fingerprint_hash == identity.fingerprint_hash,
        )
    )
    if visitor is None:
        try:
            with db.begin_nested():
                visitor = PromotionVisitor(
                    tenant_id=tenant_id,
                    fingerprint_hash=identity.fingerprint_hash,
                    fingerprint_version=identity.version,
                    fingerprint_quality=identity.quality,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                db.add(visitor)
                db.flush()
        except IntegrityError:
            visitor = db.scalar(
                select(PromotionVisitor).where(
                    PromotionVisitor.tenant_id == tenant_id,
                    PromotionVisitor.fingerprint_hash == identity.fingerprint_hash,
                )
            )
            if visitor is None:
                raise
    visitor.last_seen_at = now
    visitor.fingerprint_version = identity.version
    visitor.fingerprint_quality = identity.quality
    return visitor, identity
