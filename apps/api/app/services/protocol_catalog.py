from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from urllib.parse import quote

import httpx


_CACHE_TTL = timedelta(minutes=10)
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[datetime, dict[str, object]]] = {}


def is_prerelease_version(version: str) -> bool:
    return "-" in version.split("+", 1)[0]


def npm_package_catalog(package_name: str) -> dict[str, object]:
    now = datetime.now(UTC)
    with _CACHE_LOCK:
        cached = _CACHE.get(package_name)
        if cached and cached[0] > now:
            return dict(cached[1])

    checked_at = now.isoformat()
    result: dict[str, object]
    try:
        response = httpx.get(
            f"https://registry.npmjs.org/{quote(package_name, safe='')}",
            timeout=5.0,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        tags = payload.get("dist-tags") if isinstance(payload, dict) else None
        if not isinstance(tags, dict):
            raise ValueError("registry response has no dist-tags")
        versions = payload.get("versions")
        published = payload.get("time")
        if not isinstance(versions, dict):
            raise ValueError("registry response has no versions")
        published = published if isinstance(published, dict) else {}
        version_names = sorted(
            (str(version) for version in versions),
            key=lambda version: str(published.get(version) or ""),
            reverse=True,
        )
        normalized_tags = {
            str(name): str(version)
            for name, version in tags.items()
            if name and version
        }
        stable_versions = [
            version
            for version in version_names
            if not is_prerelease_version(version)
        ]
        preview_versions = [
            version
            for version in version_names
            if is_prerelease_version(version)
        ]
        result = {
            "latest": normalized_tags.get("latest"),
            "latestStable": stable_versions[0] if stable_versions else None,
            "latestPreview": preview_versions[0] if preview_versions else None,
            "tags": normalized_tags,
            "versions": version_names,
            "stableVersions": stable_versions,
            "previewVersions": preview_versions,
            "checkedAt": checked_at,
            "error": None,
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        result = {
            "latest": None,
            "latestStable": None,
            "latestPreview": None,
            "tags": {},
            "versions": [],
            "stableVersions": [],
            "previewVersions": [],
            "checkedAt": checked_at,
            "error": f"远程版本检查失败：{type(exc).__name__}",
        }

    with _CACHE_LOCK:
        _CACHE[package_name] = (now + _CACHE_TTL, result)
    return dict(result)


def npm_version_summary(package_name: str) -> dict[str, str | None]:
    catalog = npm_package_catalog(package_name)

    def optional_text(value: object) -> str | None:
        return str(value) if value else None

    return {
        "latestStable": optional_text(catalog.get("latestStable")),
        "latestPreview": optional_text(catalog.get("latestPreview")),
        "checkedAt": optional_text(catalog.get("checkedAt")),
        "error": optional_text(catalog.get("error")),
    }
