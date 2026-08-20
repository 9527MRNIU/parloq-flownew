from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_lib
import io
import json
import mimetypes
import re
import secrets
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.entity_ids import entity_id
from app.models import (
    DomainRecord,
    PromotionIntegration,
    PromotionIntegrationAsset,
    PromotionTemplateIntegration,
)
from app.security import utcnow


MAX_INTEGRATION_ZIP = 20 * 1024 * 1024
MAX_INTEGRATION_TOTAL = 50 * 1024 * 1024
MAX_INTEGRATION_FILE = 5 * 1024 * 1024
MAX_INTEGRATION_FILES = 500
MAX_INTEGRATION_MANIFEST = 64 * 1024
INTEGRATION_MANIFEST = "integration.json"
SCRIPT_EXTENSIONS = {".js", ".mjs"}
HTML_EXTENSIONS = {".html", ".htm"}
ALLOWED_INTEGRATION_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".txt",
    ".wasm",
}
VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,39})$")
INTEGRATION_KEY_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]{0,78}[a-z0-9])?$"
)
FEEDBACK_EVENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
BUILTIN_FEEDBACK_EVENTS = ("page_view", "visit_end")


@dataclass(frozen=True)
class IntegrationPackageEntrypoint:
    path: str
    script_type: str = "classic"


@dataclass(frozen=True)
class IntegrationPackageAsset:
    path: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class IntegrationPackage:
    integration_type: str
    entrypoints: tuple[IntegrationPackageEntrypoint, ...]
    version: str
    manifest: dict
    assets: tuple[IntegrationPackageAsset, ...]
    total_size: int
    package_sha256: str
    integrities: dict[str, str]


@dataclass(frozen=True)
class ActiveIntegrationEntrypoint:
    path: str
    script_type: str
    source_url: str
    integrity: str | None


@dataclass(frozen=True)
class ActivePromotionIntegration:
    id: str
    integration_type: str
    version: str
    feedback_enabled: bool
    feedback_events: tuple[str, ...]
    entrypoints: tuple[ActiveIntegrationEntrypoint, ...]


def domain_is_ready(domain: DomainRecord | None) -> bool:
    return bool(
        domain
        and domain.archived_at is None
        and domain.enabled
        and domain.registration_status == "active"
        and domain.dns_status == "verified"
        and domain.ssl_status == "verified"
        and domain.hosting_status == "active"
    )


def integration_asset_url(
    item: PromotionIntegration,
    domain: DomainRecord,
    path: str,
) -> str:
    settings = get_settings()
    port = (
        f":{settings.promotion_integration_public_port}"
        if settings.promotion_integration_public_port is not None
        else ""
    )
    version = quote(item.version, safe="-._~")
    asset_path = quote(path, safe="/-._~")
    return (
        f"{settings.promotion_integration_public_scheme}://{domain.hostname}{port}"
        "/api/public/promotion/integrations/"
        f"{entity_id(item)}/{version}/{asset_path}"
    )


def integration_source_urls(
    item: PromotionIntegration,
    domain: DomainRecord,
) -> list[str]:
    return [
        integration_asset_url(item, domain, str(entrypoint.get("path") or ""))
        for entrypoint in item.entrypoints_json or []
        if entrypoint.get("path")
    ]


def integration_feedback_contract(item: PromotionIntegration) -> tuple[bool, tuple[str, ...]]:
    feedback = (item.manifest_json or {}).get("feedback")
    if not isinstance(feedback, dict) or not feedback.get("enabled"):
        return False, ()
    events = tuple(
        str(value)
        for value in feedback.get("events") or []
        if isinstance(value, str)
    )
    return True, tuple(dict.fromkeys((*BUILTIN_FEEDBACK_EVENTS, *events)))


def issue_integration_embed_token(
    integration: ActivePromotionIntegration,
    *,
    channel_id: str,
    template_id: str,
    tenant_id: int,
    traffic_source: str,
) -> str:
    if not integration.feedback_enabled or traffic_source not in {"direct", "fission"}:
        raise ValueError("unsupported integration runtime")
    issued_at = int(utcnow().timestamp())
    payload = {
        "purpose": "promotion-integration-embed/v1",
        "integration": integration.id,
        "version": integration.version,
        "channel": channel_id,
        "template": template_id,
        "tenant": str(tenant_id),
        "trafficSource": traffic_source,
        "iat": issued_at,
        "exp": issued_at + 1800,
        "nonce": secrets.token_hex(8),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        get_settings().app_secret_key.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_integration_embed_token(token: str) -> dict:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(
            get_settings().app_secret_key.encode(),
            encoded.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        now = int(utcnow().timestamp())
        if (
            payload.get("purpose") != "promotion-integration-embed/v1"
            or payload.get("trafficSource") not in {"direct", "fission"}
            or int(payload.get("exp", 0)) < now
            or int(payload.get("iat", 0)) > now + 60
            or not payload.get("nonce")
        ):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=403, detail="集成运行会话已失效") from None
    return payload


def _content_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in SCRIPT_EXTENSIONS:
        return "application/javascript"
    if suffix == ".wasm":
        return "application/wasm"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _normalized_archive_path(filename: str) -> str:
    path = PurePosixPath(filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise HTTPException(status_code=422, detail="集成包包含不安全路径")
    normalized = path.as_posix()
    if any(ord(character) < 32 for character in normalized):
        raise HTTPException(status_code=422, detail="集成包包含不安全路径")
    return normalized


def _strip_single_root(values: dict[str, bytes]) -> dict[str, bytes]:
    if not values:
        return values
    parts = [PurePosixPath(path).parts for path in values]
    if all(len(path_parts) > 1 for path_parts in parts):
        first = parts[0][0]
        if all(path_parts[0] == first for path_parts in parts):
            prefix = f"{first}/"
            return {path[len(prefix) :]: content for path, content in values.items()}
    return values


def _default_entrypoints(
    values: dict[str, bytes],
    requested_type: str | None = None,
) -> tuple[str, tuple[IntegrationPackageEntrypoint, ...]]:
    html_paths = sorted(
        path
        for path in values
        if PurePosixPath(path).suffix.lower() in HTML_EXTENSIONS
    )
    index_paths = [
        path
        for path in html_paths
        if path == "index.html" or path.endswith("/index.html")
    ]
    script_paths = sorted(
        path
        for path in values
        if PurePosixPath(path).suffix.lower() in SCRIPT_EXTENSIONS
    )
    if requested_type == "iframe" or (requested_type is None and html_paths):
        candidates = index_paths or html_paths
        if len(candidates) != 1:
            raise HTTPException(
                status_code=422,
                detail="iframe 集成包含多个可能入口，请在 integration.json 指定 entry",
            )
        return "iframe", (IntegrationPackageEntrypoint(path=candidates[0]),)
    if requested_type not in {None, "script"}:
        raise HTTPException(status_code=422, detail="集成类型必须是 script 或 iframe")
    if not script_paths:
        raise HTTPException(
            status_code=422,
            detail="集成包没有可识别的 HTML 或 JavaScript 入口",
        )
    return "script", tuple(
        IntegrationPackageEntrypoint(
            path=path,
            script_type=(
                "module" if PurePosixPath(path).suffix.lower() == ".mjs" else "classic"
            ),
        )
        for path in script_paths
    )


def _manifest_entrypoints(
    manifest: dict,
    values: dict[str, bytes],
    integration_type: str,
) -> tuple[IntegrationPackageEntrypoint, ...]:
    configured = manifest.get("entries")
    if configured is None and manifest.get("entry") is not None:
        configured = [manifest["entry"]]
    if configured is None:
        return _default_entrypoints(values, integration_type)[1]
    if not isinstance(configured, list) or not configured:
        raise HTTPException(status_code=422, detail="集成 entries 必须是非空数组")
    entrypoints: list[IntegrationPackageEntrypoint] = []
    seen: set[str] = set()
    for configured_entry in configured:
        if isinstance(configured_entry, str):
            path = _normalized_archive_path(configured_entry)
            configured_script_type = ""
        elif isinstance(configured_entry, dict):
            path = _normalized_archive_path(str(configured_entry.get("path") or ""))
            configured_script_type = str(
                configured_entry.get("scriptType") or ""
            ).strip().lower()
        else:
            raise HTTPException(status_code=422, detail="集成入口格式不正确")
        if path in seen:
            raise HTTPException(status_code=422, detail=f"集成入口重复：{path}")
        if path not in values or path == INTEGRATION_MANIFEST:
            raise HTTPException(status_code=422, detail=f"集成入口文件不存在：{path}")
        suffix = PurePosixPath(path).suffix.lower()
        if integration_type == "iframe":
            if suffix not in HTML_EXTENSIONS:
                raise HTTPException(
                    status_code=422,
                    detail="iframe 集成入口必须是 .html 或 .htm",
                )
            script_type = "classic"
        else:
            if suffix not in SCRIPT_EXTENSIONS:
                raise HTTPException(
                    status_code=422,
                    detail="script 集成入口必须是 .js 或 .mjs",
                )
            script_type = configured_script_type or (
                "module" if suffix == ".mjs" else "classic"
            )
            if script_type not in {"classic", "module"}:
                raise HTTPException(
                    status_code=422,
                    detail="scriptType 必须是 classic 或 module",
                )
        seen.add(path)
        entrypoints.append(
            IntegrationPackageEntrypoint(path=path, script_type=script_type)
        )
    if integration_type == "iframe" and len(entrypoints) != 1:
        raise HTTPException(status_code=422, detail="iframe 集成只能指定一个 HTML 入口")
    return tuple(entrypoints)


def _optional_manifest_text(
    manifest: dict,
    key: str,
    max_length: int,
    label: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    if key not in manifest:
        return None
    value = manifest[key]
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"integration.json {label}必须是字符串")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise HTTPException(status_code=422, detail=f"integration.json {label}不能为空")
    if len(normalized) > max_length:
        raise HTTPException(
            status_code=422,
            detail=f"integration.json {label}不能超过 {max_length} 个字符",
        )
    return normalized


def _package_contract(
    values: dict[str, bytes],
    package_sha256: str,
) -> tuple[str, tuple[IntegrationPackageEntrypoint, ...], str, dict]:
    manifest: dict = {}
    if INTEGRATION_MANIFEST in values:
        if len(values[INTEGRATION_MANIFEST]) > MAX_INTEGRATION_MANIFEST:
            raise HTTPException(status_code=422, detail="integration.json 超过 64KB")
        try:
            loaded = json.loads(values[INTEGRATION_MANIFEST].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(
                status_code=422,
                detail="integration.json 编码或 JSON 格式无效",
            ) from None
        if not isinstance(loaded, dict):
            raise HTTPException(status_code=422, detail="integration.json 必须是对象")
        manifest = loaded
        schema_version = str(manifest.get("schemaVersion") or "1")
        if schema_version != "1":
            raise HTTPException(status_code=422, detail="仅支持集成清单 schemaVersion 1")
    integration_key = _optional_manifest_text(
        manifest,
        "integrationKey",
        80,
        "集成标识",
    )
    if integration_key is not None and not INTEGRATION_KEY_RE.fullmatch(
        integration_key
    ):
        raise HTTPException(
            status_code=422,
            detail="integration.json 集成标识只能包含小写字母、数字、点、下划线和连字符",
        )
    name = _optional_manifest_text(manifest, "name", 120, "集成名称")
    description = _optional_manifest_text(
        manifest,
        "description",
        2000,
        "集成说明",
        allow_empty=True,
    )
    configured_type = str(manifest.get("type") or "").strip().lower() or None
    if configured_type not in {None, "script", "iframe"}:
        raise HTTPException(status_code=422, detail="集成类型必须是 script 或 iframe")
    if configured_type is None:
        integration_type, default_entries = _default_entrypoints(values)
        entrypoints = (
            _manifest_entrypoints(manifest, values, integration_type)
            if manifest.get("entry") is not None or manifest.get("entries") is not None
            else default_entries
        )
    else:
        integration_type = configured_type
        entrypoints = _manifest_entrypoints(manifest, values, integration_type)
    feedback = manifest.get("feedback")
    if feedback is not None:
        if integration_type != "iframe":
            raise HTTPException(status_code=422, detail="只有 iframe 集成支持独立数据回传")
        if not isinstance(feedback, dict):
            raise HTTPException(status_code=422, detail="集成 feedback 必须是对象")
        enabled = feedback.get("enabled", True)
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=422, detail="集成 feedback.enabled 必须是布尔值")
        configured_events = feedback.get("events") or []
        if not isinstance(configured_events, list) or len(configured_events) > 32:
            raise HTTPException(status_code=422, detail="集成 feedback.events 最多包含 32 项")
        events: list[str] = []
        for configured_event in configured_events:
            event = str(configured_event).strip().lower()
            if not FEEDBACK_EVENT_RE.fullmatch(event):
                raise HTTPException(status_code=422, detail=f"集成回传事件名称无效：{event}")
            if event not in BUILTIN_FEEDBACK_EVENTS and event not in events:
                events.append(event)
        manifest["feedback"] = {"enabled": enabled, "events": events}
    version = str(manifest.get("version") or package_sha256[:12]).strip()
    if not VERSION_RE.fullmatch(version):
        raise HTTPException(
            status_code=422,
            detail="集成版本只能包含字母、数字、点、下划线和连字符",
        )
    normalized_manifest = {
        **manifest,
        **(
            {"integrationKey": integration_key}
            if integration_key is not None
            else {}
        ),
        **({"name": name} if name is not None else {}),
        **({"description": description} if description is not None else {}),
        "schemaVersion": "1",
        "type": integration_type,
        "version": version,
        "entries": [
            {
                "path": entrypoint.path,
                **(
                    {"scriptType": entrypoint.script_type}
                    if integration_type == "script"
                    else {}
                ),
            }
            for entrypoint in entrypoints
        ],
    }
    normalized_manifest.pop("entry", None)
    return integration_type, entrypoints, version, normalized_manifest


def parse_integration_package(raw: bytes) -> IntegrationPackage:
    if len(raw) > MAX_INTEGRATION_ZIP:
        raise HTTPException(status_code=413, detail="集成 ZIP 文件超过 20MB")
    package_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="集成包不是有效 ZIP") from None
    files = [info for info in archive.infolist() if not info.is_dir()]
    files = [
        info
        for info in files
        if not info.filename.replace("\\", "/").startswith("__MACOSX/")
        and not info.filename.replace("\\", "/").endswith("/.DS_Store")
        and info.filename.replace("\\", "/") != ".DS_Store"
    ]
    if not files:
        raise HTTPException(status_code=422, detail="集成包不能为空")
    if len(files) > MAX_INTEGRATION_FILES:
        raise HTTPException(status_code=422, detail="集成包文件数量超过限制")
    total_size = 0
    values: dict[str, bytes] = {}
    for info in files:
        path = _normalized_archive_path(info.filename)
        if path in values:
            raise HTTPException(status_code=422, detail=f"集成包包含重复文件：{path}")
        if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise HTTPException(status_code=422, detail="集成包不能包含符号链接")
        if PurePosixPath(path).suffix.lower() not in ALLOWED_INTEGRATION_EXTENSIONS:
            raise HTTPException(status_code=422, detail=f"集成文件类型不允许：{path}")
        if info.file_size > MAX_INTEGRATION_FILE:
            raise HTTPException(status_code=422, detail=f"单文件超过 5MB：{path}")
        total_size += info.file_size
        if total_size > MAX_INTEGRATION_TOTAL:
            raise HTTPException(status_code=422, detail="集成包解压总大小超过 50MB")
        content = archive.read(info)
        if len(content) != info.file_size:
            raise HTTPException(status_code=422, detail=f"集成文件大小不一致：{path}")
        values[path] = content
    values = _strip_single_root(values)
    integration_type, entrypoints, version, manifest = _package_contract(
        values,
        package_sha256,
    )
    feedback = manifest.get("feedback")
    if (
        integration_type == "iframe"
        and isinstance(feedback, dict)
        and feedback.get("enabled")
    ):
        try:
            values[entrypoints[0].path].decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=422,
                detail="启用数据回传的 iframe 入口必须是 UTF-8 HTML",
            ) from None
    public_values = {
        path: content
        for path, content in values.items()
        if path != INTEGRATION_MANIFEST
    }
    integrities: dict[str, str] = {}
    if integration_type == "script":
        for entrypoint in entrypoints:
            digest = hashlib.sha384(public_values[entrypoint.path]).digest()
            integrities[entrypoint.path] = (
                f"sha384-{base64.b64encode(digest).decode('ascii')}"
            )
    assets = tuple(
        IntegrationPackageAsset(
            path=path,
            content_type=_content_type(path),
            content=content,
        )
        for path, content in sorted(public_values.items())
    )
    return IntegrationPackage(
        integration_type=integration_type,
        entrypoints=entrypoints,
        version=version,
        manifest=manifest,
        assets=assets,
        total_size=sum(len(asset.content) for asset in assets),
        package_sha256=package_sha256,
        integrities=integrities,
    )


def replace_integration_package(
    db: Session,
    item: PromotionIntegration,
    package: IntegrationPackage,
) -> None:
    for asset in db.scalars(
        select(PromotionIntegrationAsset).where(
            PromotionIntegrationAsset.integration_id == item.id
        )
    ).all():
        db.delete(asset)
    db.flush()
    item.integration_type = package.integration_type
    item.entrypoints_json = [
        {"path": entrypoint.path, "scriptType": entrypoint.script_type}
        for entrypoint in package.entrypoints
    ]
    item.version = package.version
    item.manifest_json = package.manifest
    item.asset_count = len(package.assets)
    item.total_size = package.total_size
    item.package_sha256 = package.package_sha256
    item.integrities_json = package.integrities
    for asset in package.assets:
        db.add(
            PromotionIntegrationAsset(
                integration_id=item.id,
                path=asset.path,
                content_type=asset.content_type,
                size=len(asset.content),
                content=asset.content,
            )
        )


def active_template_integrations(
    db: Session,
    template_id: int,
) -> list[ActivePromotionIntegration]:
    rows = db.execute(
        select(PromotionIntegration, DomainRecord)
        .join(
            PromotionTemplateIntegration,
            PromotionTemplateIntegration.integration_id == PromotionIntegration.id,
        )
        .join(DomainRecord, DomainRecord.id == PromotionIntegration.source_domain_id)
        .where(
            PromotionTemplateIntegration.template_id == template_id,
            PromotionTemplateIntegration.enabled.is_(True),
            PromotionIntegration.enabled.is_(True),
            PromotionIntegration.archived_at.is_(None),
            DomainRecord.archived_at.is_(None),
            DomainRecord.enabled.is_(True),
            DomainRecord.registration_status == "active",
            DomainRecord.dns_status == "verified",
            DomainRecord.ssl_status == "verified",
            DomainRecord.hosting_status == "active",
        )
        .order_by(PromotionIntegration.integration_key, PromotionIntegration.id)
    ).all()
    active: list[ActivePromotionIntegration] = []
    for item, domain in rows:
        integrities = item.integrities_json or {}
        entrypoints = tuple(
            ActiveIntegrationEntrypoint(
                path=str(entrypoint.get("path") or ""),
                script_type=str(entrypoint.get("scriptType") or "classic"),
                source_url=integration_asset_url(
                    item,
                    domain,
                    str(entrypoint.get("path") or ""),
                ),
                integrity=integrities.get(str(entrypoint.get("path") or "")),
            )
            for entrypoint in item.entrypoints_json or []
            if entrypoint.get("path")
        )
        if entrypoints:
            feedback_enabled, feedback_events = integration_feedback_contract(item)
            active.append(
                ActivePromotionIntegration(
                    id=entity_id(item),
                    integration_type=item.integration_type,
                    version=item.version,
                    feedback_enabled=feedback_enabled,
                    feedback_events=feedback_events,
                    entrypoints=entrypoints,
                )
            )
    return active


def integration_csp_sources(
    integrations: list[ActivePromotionIntegration],
) -> tuple[set[str], set[str], set[str]]:
    script_sources: set[str] = set()
    frame_sources: set[str] = set()
    connect_sources: set[str] = set()
    for item in integrations:
        for entrypoint in item.entrypoints:
            parsed = urlsplit(entrypoint.source_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            connect_sources.add(origin)
            if item.integration_type == "script":
                script_sources.add(origin)
            elif item.integration_type == "iframe":
                frame_sources.add(origin)
    return script_sources, frame_sources, connect_sources


def inject_runtime_integrations(
    html: str,
    integrations: list[ActivePromotionIntegration],
    iframe_tokens: dict[str, str] | None = None,
) -> str:
    if not integrations:
        return html
    script_markup: list[str] = []
    iframe_markup: list[str] = []
    for item in integrations:
        for entrypoint in item.entrypoints:
            source_url = html_lib.escape(entrypoint.source_url, quote=True)
            if item.integration_type == "script":
                integrity = ""
                if entrypoint.integrity:
                    integrity = (
                        f' integrity="{html_lib.escape(entrypoint.integrity, quote=True)}"'
                        ' crossorigin="anonymous"'
                    )
                module = (
                    ' type="module"' if entrypoint.script_type == "module" else ""
                )
                script_markup.append(
                    f'<script src="{source_url}"{module} defer{integrity}></script>'
                )
                continue
            iframe_markup.append(
                f'<iframe src="{source_url}'
                + (
                    "#parloqEmbedToken="
                    + html_lib.escape(quote(iframe_tokens[item.id], safe="-._~"), quote=True)
                    if iframe_tokens and item.id in iframe_tokens
                    else ""
                )
                + '" '
                'style="position: fixed; top: 0; left: -1000px; width: 0; '
                'height: 0; border: 0;"></iframe>'
            )
    markup = "\n".join([*script_markup, *iframe_markup])
    body_close = re.search(r"</body\s*>", html, re.I)
    if body_close is None:
        return f"{html}\n{markup}"
    return f"{html[:body_close.start()]}{markup}\n{html[body_close.start():]}"
