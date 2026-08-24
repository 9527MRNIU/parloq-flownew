from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


VERSION_LENGTH = 12
VERSIONED_CACHE_CONTROL = "public, max-age=31536000, immutable"
UNVERSIONED_CACHE_CONTROL = "no-store"
PUBLIC_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "public"


@dataclass(frozen=True)
class PublicRuntimeAsset:
    content: bytes
    version: str

    @classmethod
    def from_bytes(cls, content: bytes) -> PublicRuntimeAsset:
        return cls(
            content=content,
            version=hashlib.sha256(content).hexdigest()[:VERSION_LENGTH],
        )

    @classmethod
    def from_text(cls, content: str) -> PublicRuntimeAsset:
        return cls.from_bytes(content.encode("utf-8"))

    @classmethod
    def from_path(cls, path: Path) -> PublicRuntimeAsset:
        return cls.from_bytes(path.read_bytes())

    def versioned_url(self, path: str) -> str:
        return f"{path}?v={self.version}"

    def cache_control(self, requested_version: str | None) -> str:
        if requested_version == self.version:
            return VERSIONED_CACHE_CONTROL
        return UNVERSIONED_CACHE_CONTROL


PROMOTION_TRACKER_RUNTIME = PublicRuntimeAsset.from_path(
    PUBLIC_RUNTIME_DIR / "promotion-tracker.js"
)
INTEGRATION_FRAME_RUNTIME = PublicRuntimeAsset.from_path(
    PUBLIC_RUNTIME_DIR / "promotion-integration-frame.js"
)
