from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    SystemCredential,
    SystemPlatformConfiguration,
    SystemRepositorySnapshot,
)
from app.security import decrypt_secret, utcnow
from app.services.platform_clients import PlatformClientError


GITHUB_PLATFORM_KEY = "github"
GITHUB_CREDENTIAL_KEY = "access_token"
GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITHUB_REF = "main"
DEFAULT_CATALOG_PATH = "artifacts/catalog.json"
REMOTE_SOURCE_KEY = "_parloqRepositorySource"
MAX_CATALOG_BYTES = 1024 * 1024
MAX_REMOTE_FILES = 500
MAX_REMOTE_FILE_BYTES = 5 * 1024 * 1024
MAX_REMOTE_TOTAL_BYTES = 50 * 1024 * 1024
MAX_REMOTE_ARCHIVE_BYTES = 20 * 1024 * 1024
SEQUENCE_RE = re.compile(r"^[0-9]{4}$")
REPOSITORY_PART_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GitHubRepositoryConfigurationError(PlatformClientError):
    pass


@dataclass(frozen=True)
class GitHubTreeFile:
    path: str
    sha: str
    size: int
    mode: str = "100644"


@dataclass(frozen=True)
class GitHubRemoteArtifact:
    sequence: str
    kind: str
    slug: str
    source: str
    manifest_path: str
    name: str
    description: str | None
    version: str
    integration_key: str | None
    integration_type: str | None
    source_sha: str
    files: tuple[GitHubTreeFile, ...]


@dataclass(frozen=True)
class GitHubRepositorySnapshot:
    repository: str
    ref: str
    commit_sha: str
    artifacts: tuple[GitHubRemoteArtifact, ...]


def _snapshot_payload(snapshot: GitHubRepositorySnapshot) -> dict:
    return {
        "repository": snapshot.repository,
        "ref": snapshot.ref,
        "commitSha": snapshot.commit_sha,
        "artifacts": [
            {
                "sequence": artifact.sequence,
                "kind": artifact.kind,
                "slug": artifact.slug,
                "source": artifact.source,
                "manifestPath": artifact.manifest_path,
                "name": artifact.name,
                "description": artifact.description,
                "version": artifact.version,
                "integrationKey": artifact.integration_key,
                "integrationType": artifact.integration_type,
                "sourceSha": artifact.source_sha,
                "files": [
                    {
                        "path": file.path,
                        "sha": file.sha,
                        "size": file.size,
                        "mode": file.mode,
                    }
                    for file in artifact.files
                ],
            }
            for artifact in snapshot.artifacts
        ],
    }


def _snapshot_from_payload(payload: dict) -> GitHubRepositorySnapshot:
    artifacts: list[GitHubRemoteArtifact] = []
    for value in payload.get("artifacts") or []:
        if not isinstance(value, dict):
            raise ValueError("invalid repository snapshot artifact")
        files = tuple(
            GitHubTreeFile(
                path=str(file.get("path") or ""),
                sha=str(file.get("sha") or ""),
                size=int(file.get("size") or 0),
                mode=str(file.get("mode") or "100644"),
            )
            for file in value.get("files") or []
            if isinstance(file, dict)
        )
        artifacts.append(
            GitHubRemoteArtifact(
                sequence=str(value.get("sequence") or ""),
                kind=str(value.get("kind") or ""),
                slug=str(value.get("slug") or ""),
                source=str(value.get("source") or ""),
                manifest_path=str(value.get("manifestPath") or ""),
                name=str(value.get("name") or ""),
                description=(
                    str(value["description"])
                    if value.get("description") is not None
                    else None
                ),
                version=str(value.get("version") or "1"),
                integration_key=(
                    str(value["integrationKey"])
                    if value.get("integrationKey") is not None
                    else None
                ),
                integration_type=(
                    str(value["integrationType"])
                    if value.get("integrationType") is not None
                    else None
                ),
                source_sha=str(value.get("sourceSha") or ""),
                files=files,
            )
        )
    snapshot = GitHubRepositorySnapshot(
        repository=str(payload.get("repository") or ""),
        ref=str(payload.get("ref") or ""),
        commit_sha=str(payload.get("commitSha") or ""),
        artifacts=tuple(artifacts),
    )
    if not snapshot.repository or not snapshot.ref or not snapshot.commit_sha:
        raise ValueError("invalid repository snapshot")
    return snapshot


def _filtered_snapshot(
    snapshot: GitHubRepositorySnapshot,
    kind: str | None,
) -> GitHubRepositorySnapshot:
    if kind not in {None, "template", "integration"}:
        raise ValueError("unsupported repository artifact kind")
    if kind is None:
        return snapshot
    return GitHubRepositorySnapshot(
        repository=snapshot.repository,
        ref=snapshot.ref,
        commit_sha=snapshot.commit_sha,
        artifacts=tuple(
            artifact for artifact in snapshot.artifacts if artifact.kind == kind
        ),
    )


def normalize_github_repository(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        raise ValueError("请填写 GitHub 仓库")
    if "://" in raw:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("GitHub 仓库地址格式不正确")
        raw = parsed.path.strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    parts = raw.split("/")
    if len(parts) != 2 or any(REPOSITORY_PART_RE.fullmatch(part) is None for part in parts):
        raise ValueError("GitHub 仓库请填写 owner/repository 或完整 HTTPS 地址")
    return f"{parts[0]}/{parts[1]}"


def normalize_github_ref(value: str | None) -> str:
    ref = (value or DEFAULT_GITHUB_REF).strip()
    if (
        not ref
        or len(ref) > 255
        or any(ord(character) < 32 for character in ref)
        or ref.startswith("-")
        or "\\" in ref
    ):
        raise ValueError("GitHub 分支或标签格式不正确")
    return ref


def normalize_repository_path(value: str | None, *, default: str = "") -> str:
    raw = (value or default).strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or len(raw) > 512
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.startswith(".") for part in path.parts)
    ):
        raise ValueError("仓库目录路径格式不正确")
    return path.as_posix()


def _public_source_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    filename = parts[-1] if parts else ""
    return bool(
        parts
        and not any(part.startswith(".") for part in parts)
        and re.match(r"^readme(?:\.|$)", filename, re.I) is None
    )


def repository_source_metadata(
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> dict[str, str]:
    return {
        "provider": "github",
        "repository": snapshot.repository,
        "ref": snapshot.ref,
        "kind": artifact.kind,
        "sequence": artifact.sequence,
        "slug": artifact.slug,
        "source": artifact.source,
        "commitSha": snapshot.commit_sha,
        "sourceSha": artifact.source_sha,
    }


def remote_artifact_row(
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> dict:
    repository_url = f"https://github.com/{snapshot.repository}"
    source_url = (
        f"{repository_url}/tree/{quote(snapshot.ref, safe='')}/{artifact.source}"
    )
    return {
        "id": f"{artifact.kind}:{artifact.sequence}",
        "sequence": artifact.sequence,
        "kind": artifact.kind,
        "slug": artifact.slug,
        "source": artifact.source,
        "sourceUrl": source_url,
        "name": artifact.name,
        "description": artifact.description,
        "version": artifact.version,
        "integrationKey": artifact.integration_key,
        "type": artifact.integration_type,
        "sourceSha": artifact.source_sha,
        "commitSha": snapshot.commit_sha,
        "repository": snapshot.repository,
        "ref": snapshot.ref,
        "fileCount": len(artifact.files),
        "totalSize": sum(file.size for file in artifact.files),
    }


def with_repository_source(
    manifest: dict,
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> dict:
    return {
        **manifest,
        REMOTE_SOURCE_KEY: repository_source_metadata(snapshot, artifact),
    }


def stored_repository_source(manifest: dict | None) -> dict[str, str]:
    value = (manifest or {}).get(REMOTE_SOURCE_KEY)
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, (str, int))
    }


def repository_source_matches_artifact(
    source: dict[str, str],
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> bool:
    if not (
        source.get("provider") == "github"
        and source.get("repository") == snapshot.repository
        and source.get("kind") == artifact.kind
    ):
        return False
    source_slug = source.get("slug")
    if source_slug:
        return source_slug == artifact.slug
    return source.get("sequence") == artifact.sequence


def repository_local_status(
    manifest: dict | None,
    version: str,
    snapshot: GitHubRepositorySnapshot,
    artifact: GitHubRemoteArtifact,
) -> str:
    source = stored_repository_source(manifest)
    linked = repository_source_matches_artifact(source, snapshot, artifact)
    if linked and source.get("sourceSha") == artifact.source_sha:
        return "current"
    if linked and version == artifact.version:
        return "conflict"
    if not linked and version == artifact.version:
        return "current"
    return "update"


class GitHubRepositoryClient:
    def __init__(
        self,
        token: str,
        *,
        repository: str,
        ref: str = DEFAULT_GITHUB_REF,
        catalog_path: str = DEFAULT_CATALOG_PATH,
        client: httpx.Client | None = None,
    ) -> None:
        self.repository = normalize_github_repository(repository)
        self.ref = normalize_github_ref(ref)
        self.catalog_path = normalize_repository_path(
            catalog_path,
            default=DEFAULT_CATALOG_PATH,
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=GITHUB_API_URL,
            timeout=httpx.Timeout(20, connect=5),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "parloq-flow-repository-sync",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict:
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise PlatformClientError("GitHub 请求超时，请稍后重试", retryable=True) from error
        except httpx.HTTPError as error:
            raise PlatformClientError("无法连接 GitHub，请检查网络") from error
        if response.status_code == 401:
            raise PlatformClientError("GitHub Token 无效或已失效")
        if response.status_code == 403:
            raise PlatformClientError("GitHub Token 没有该私人仓库的只读权限")
        if response.status_code == 404:
            raise PlatformClientError("GitHub 仓库、分支或文件不存在")
        if response.status_code >= 500:
            raise PlatformClientError("GitHub 服务暂时不可用", retryable=True)
        if response.status_code >= 400:
            raise PlatformClientError(f"GitHub 请求失败（HTTP {response.status_code}）")
        try:
            payload = response.json()
        except ValueError as error:
            raise PlatformClientError("GitHub 返回了无法识别的数据") from error
        if not isinstance(payload, dict):
            raise PlatformClientError("GitHub 返回的数据格式不正确")
        return payload

    def verify_connection(self) -> dict[str, str]:
        owner, repository = self.repository.split("/", 1)
        payload = self._get_json(f"/repos/{quote(owner)}/{quote(repository)}")
        self.scan(kind=None, include_manifests=False)
        return {
            "repository": str(payload.get("full_name") or self.repository),
            "defaultBranch": str(payload.get("default_branch") or ""),
        }

    def _commit_and_tree(self) -> tuple[str, tuple[GitHubTreeFile, ...]]:
        owner, repository = self.repository.split("/", 1)
        commit = self._get_json(
            f"/repos/{quote(owner)}/{quote(repository)}/commits/{quote(self.ref, safe='')}"
        )
        commit_sha = str(commit.get("sha") or "")
        tree_sha = str((commit.get("commit") or {}).get("tree", {}).get("sha") or "")
        if not commit_sha or not tree_sha:
            raise PlatformClientError("GitHub 提交信息不完整")
        tree = self._get_json(
            f"/repos/{quote(owner)}/{quote(repository)}/git/trees/{quote(tree_sha)}",
            params={"recursive": "1"},
        )
        if tree.get("truncated"):
            raise PlatformClientError("GitHub 仓库文件过多，无法完整读取目录")
        files: list[GitHubTreeFile] = []
        for value in tree.get("tree") or []:
            if not isinstance(value, dict) or value.get("type") != "blob":
                continue
            path = str(value.get("path") or "")
            sha = str(value.get("sha") or "")
            size = int(value.get("size") or 0)
            mode = str(value.get("mode") or "100644")
            if path and sha:
                files.append(
                    GitHubTreeFile(path=path, sha=sha, size=size, mode=mode)
                )
        return commit_sha, tuple(files)

    def _blob_bytes(self, file: GitHubTreeFile, *, max_bytes: int) -> bytes:
        if file.size > max_bytes:
            raise PlatformClientError(f"仓库文件超过大小限制：{file.path}")
        owner, repository = self.repository.split("/", 1)
        payload = self._get_json(
            f"/repos/{quote(owner)}/{quote(repository)}/git/blobs/{quote(file.sha)}"
        )
        if payload.get("encoding") != "base64":
            raise PlatformClientError(f"GitHub 文件编码不受支持：{file.path}")
        try:
            content = base64.b64decode(str(payload.get("content") or ""), validate=False)
        except (ValueError, TypeError) as error:
            raise PlatformClientError(f"GitHub 文件内容损坏：{file.path}") from error
        if len(content) > max_bytes or (file.size and len(content) != file.size):
            raise PlatformClientError(f"GitHub 文件大小不一致：{file.path}")
        return content

    def _json_blob(self, file: GitHubTreeFile, *, label: str, max_bytes: int) -> dict:
        content = self._blob_bytes(file, max_bytes=max_bytes)
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PlatformClientError(f"{label} 不是有效的 UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise PlatformClientError(f"{label} 必须包含 JSON 对象")
        return payload

    def scan(
        self,
        *,
        kind: str | None,
        include_manifests: bool = True,
    ) -> GitHubRepositorySnapshot:
        if kind not in {None, "template", "integration"}:
            raise ValueError("unsupported repository artifact kind")
        commit_sha, tree_files = self._commit_and_tree()
        by_path = {file.path: file for file in tree_files}
        catalog_file = by_path.get(self.catalog_path)
        if catalog_file is None:
            raise PlatformClientError(f"仓库缺少目录清单：{self.catalog_path}")
        catalog = self._json_blob(
            catalog_file,
            label=self.catalog_path,
            max_bytes=MAX_CATALOG_BYTES,
        )
        if str(catalog.get("schemaVersion") or "") != "1":
            raise PlatformClientError("仓库目录清单版本不受支持")
        artifacts: list[GitHubRemoteArtifact] = []
        seen: set[tuple[str, str]] = set()
        for raw in catalog.get("artifacts") or []:
            if not isinstance(raw, dict):
                raise PlatformClientError("仓库目录清单包含无效项目")
            artifact_kind = str(raw.get("kind") or "")
            if artifact_kind not in {"template", "integration"}:
                continue
            if kind is not None and artifact_kind != kind:
                continue
            sequence = str(raw.get("sequence") or "")
            slug = str(raw.get("slug") or "").strip()
            if SEQUENCE_RE.fullmatch(sequence) is None or not slug:
                raise PlatformClientError("仓库项目编号或链接名称格式不正确")
            identity = (artifact_kind, sequence)
            if identity in seen:
                raise PlatformClientError(f"仓库项目编号重复：{sequence}")
            seen.add(identity)
            try:
                source = normalize_repository_path(str(raw.get("source") or ""))
                manifest_name = normalize_repository_path(
                    str(raw.get("manifest") or "")
                )
            except ValueError as error:
                raise PlatformClientError(str(error)) from error
            prefix = f"{source}/"
            source_files = tuple(
                file
                for file in tree_files
                if file.path.startswith(prefix)
                and _public_source_path(file.path[len(prefix) :])
            )
            if not source_files:
                raise PlatformClientError(f"仓库项目目录为空：{source}")
            if any(file.mode == "120000" for file in source_files):
                raise PlatformClientError(f"仓库项目不能包含符号链接：{source}")
            manifest_path = f"{source}/{manifest_name}"
            manifest_file = by_path.get(manifest_path)
            if manifest_file is None:
                raise PlatformClientError(f"仓库项目缺少清单：{manifest_path}")
            source_digest = hashlib.sha256()
            for file in sorted(source_files, key=lambda value: value.path):
                relative = file.path[len(prefix) :]
                source_digest.update(f"{relative}\0{file.sha}\0{file.size}\n".encode())
            manifest: dict = {}
            if include_manifests:
                manifest = self._json_blob(
                    manifest_file,
                    label=manifest_path,
                    max_bytes=MAX_CATALOG_BYTES,
                )
            name = str(manifest.get("name") or slug).strip()
            description_value = manifest.get("description")
            description = (
                str(description_value).strip()
                if isinstance(description_value, str) and description_value.strip()
                else None
            )
            version = str(manifest.get("version") or "1").strip()
            integration_key = (
                str(manifest.get("integrationKey") or "").strip() or None
            )
            integration_type = str(manifest.get("type") or "").strip() or None
            if include_manifests and (not name or len(name) > 120 or len(version) > 40):
                raise PlatformClientError(f"仓库项目清单字段不正确：{manifest_path}")
            if artifact_kind == "integration" and include_manifests and not integration_key:
                raise PlatformClientError(f"远程集成缺少 integrationKey：{manifest_path}")
            artifacts.append(
                GitHubRemoteArtifact(
                    sequence=sequence,
                    kind=artifact_kind,
                    slug=slug,
                    source=source,
                    manifest_path=manifest_path,
                    name=name,
                    description=description,
                    version=version,
                    integration_key=integration_key,
                    integration_type=integration_type,
                    source_sha=source_digest.hexdigest(),
                    files=source_files,
                )
            )
        return GitHubRepositorySnapshot(
            repository=self.repository,
            ref=self.ref,
            commit_sha=commit_sha,
            artifacts=tuple(
                sorted(artifacts, key=lambda value: (value.kind, value.sequence))
            ),
        )

    def archive_artifact(self, artifact: GitHubRemoteArtifact) -> bytes:
        if len(artifact.files) > MAX_REMOTE_FILES:
            raise PlatformClientError(f"远程项目文件数量超过限制：{artifact.source}")
        total = sum(file.size for file in artifact.files)
        if total > MAX_REMOTE_TOTAL_BYTES:
            raise PlatformClientError(f"远程项目总大小超过限制：{artifact.source}")
        for file in artifact.files:
            if file.size > MAX_REMOTE_FILE_BYTES:
                raise PlatformClientError(f"仓库文件超过 5MB：{file.path}")
        workers = max(1, min(8, len(artifact.files)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            contents = list(
                executor.map(
                    lambda file: self._blob_bytes(file, max_bytes=MAX_REMOTE_FILE_BYTES),
                    artifact.files,
                )
            )
        prefix = f"{artifact.source}/"
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for file, content in sorted(
                zip(artifact.files, contents),
                key=lambda value: value[0].path,
            ):
                relative = file.path[len(prefix) :]
                info = zipfile.ZipInfo(relative, date_time=(2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content, compresslevel=9)
        result = buffer.getvalue()
        if len(result) > MAX_REMOTE_ARCHIVE_BYTES:
            raise PlatformClientError(f"远程项目内容超过导入限制：{artifact.source}")
        return result


def _configured_github_repository(
    db: Session,
) -> tuple[SystemCredential, str, str, str]:
    configuration = db.scalar(
        select(SystemPlatformConfiguration).where(
            SystemPlatformConfiguration.platform_key == GITHUB_PLATFORM_KEY
        )
    )
    credential = db.scalar(
        select(SystemCredential).where(
            SystemCredential.platform_key == GITHUB_PLATFORM_KEY,
            SystemCredential.credential_key == GITHUB_CREDENTIAL_KEY,
        )
    )
    if configuration is None or not configuration.enabled or credential is None:
        raise GitHubRepositoryConfigurationError("请先在系统配置中启用 GitHub 仓库")
    settings = dict(configuration.settings_json or {})
    try:
        return (
            credential,
            normalize_github_repository(str(settings.get("repository") or "")),
            normalize_github_ref(str(settings.get("ref") or DEFAULT_GITHUB_REF)),
            normalize_repository_path(
                str(settings.get("catalogPath") or DEFAULT_CATALOG_PATH),
                default=DEFAULT_CATALOG_PATH,
            ),
        )
    except ValueError as error:
        raise GitHubRepositoryConfigurationError(str(error)) from error


def configured_github_repository_client(db: Session) -> GitHubRepositoryClient:
    credential, repository, repository_ref, catalog_path = (
        _configured_github_repository(db)
    )
    return GitHubRepositoryClient(
        decrypt_secret(credential.value_ciphertext),
        repository=repository,
        ref=repository_ref,
        catalog_path=catalog_path,
    )


def cached_github_repository_snapshot(
    db: Session,
    *,
    kind: str | None = None,
) -> tuple[GitHubRepositorySnapshot, datetime] | None:
    _credential, repository, repository_ref, catalog_path = (
        _configured_github_repository(db)
    )
    record = db.scalar(
        select(SystemRepositorySnapshot).where(
            SystemRepositorySnapshot.platform_key == GITHUB_PLATFORM_KEY
        )
    )
    if (
        record is None
        or record.repository != repository
        or record.repository_ref != repository_ref
        or record.catalog_path != catalog_path
    ):
        return None
    try:
        snapshot = _snapshot_from_payload(dict(record.payload_json or {}))
    except (TypeError, ValueError):
        return None
    if (
        snapshot.repository != repository
        or snapshot.ref != repository_ref
        or snapshot.commit_sha != record.commit_sha
    ):
        return None
    return _filtered_snapshot(snapshot, kind), record.refreshed_at


def persist_github_repository_snapshot(
    db: Session,
    snapshot: GitHubRepositorySnapshot,
    *,
    catalog_path: str,
) -> datetime:
    refreshed_at = utcnow()
    record = db.scalar(
        select(SystemRepositorySnapshot)
        .where(SystemRepositorySnapshot.platform_key == GITHUB_PLATFORM_KEY)
        .with_for_update()
    )
    if record is None:
        record = SystemRepositorySnapshot(
            platform_key=GITHUB_PLATFORM_KEY,
            repository=snapshot.repository,
            repository_ref=snapshot.ref,
            catalog_path=catalog_path,
            commit_sha=snapshot.commit_sha,
            payload_json=_snapshot_payload(snapshot),
            refreshed_at=refreshed_at,
        )
        db.add(record)
    else:
        record.repository = snapshot.repository
        record.repository_ref = snapshot.ref
        record.catalog_path = catalog_path
        record.commit_sha = snapshot.commit_sha
        record.payload_json = _snapshot_payload(snapshot)
        record.refreshed_at = refreshed_at
    try:
        db.commit()
    except IntegrityError:
        # Two first-load requests can race on the one-row platform cache.
        db.rollback()
        record = db.scalar(
            select(SystemRepositorySnapshot).where(
                SystemRepositorySnapshot.platform_key == GITHUB_PLATFORM_KEY
            )
        )
        if record is None:
            raise
        record.repository = snapshot.repository
        record.repository_ref = snapshot.ref
        record.catalog_path = catalog_path
        record.commit_sha = snapshot.commit_sha
        record.payload_json = _snapshot_payload(snapshot)
        record.refreshed_at = refreshed_at
        db.commit()
    return refreshed_at


def refresh_github_repository_snapshot(
    db: Session,
    *,
    kind: str | None = None,
) -> tuple[GitHubRepositorySnapshot, datetime]:
    client = configured_github_repository_client(db)
    try:
        snapshot = client.scan(kind=None)
        catalog_path = client.catalog_path
    finally:
        client.close()
    refreshed_at = persist_github_repository_snapshot(
        db,
        snapshot,
        catalog_path=catalog_path,
    )
    return _filtered_snapshot(snapshot, kind), refreshed_at


def github_repository_snapshot(
    db: Session,
    *,
    kind: str | None = None,
) -> tuple[GitHubRepositorySnapshot, datetime]:
    cached = cached_github_repository_snapshot(db, kind=kind)
    if cached is not None:
        return cached
    return refresh_github_repository_snapshot(db, kind=kind)


def clear_github_repository_snapshot(db: Session) -> None:
    record = db.scalar(
        select(SystemRepositorySnapshot).where(
            SystemRepositorySnapshot.platform_key == GITHUB_PLATFORM_KEY
        )
    )
    if record is not None:
        db.delete(record)
