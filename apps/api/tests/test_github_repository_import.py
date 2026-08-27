from __future__ import annotations

import base64
import io
import json
import zipfile
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

import app.routers.promotion as promotion_router
import app.routers.promotion_integrations as integration_router
import app.services.github_repository as github_repository_service
from app.services.github_repository import (
    GitHubRepositoryArtifactValidationError,
    GitHubRemoteArtifact,
    GitHubRepositoryClient,
    GitHubRepositorySnapshot,
    GitHubTreeFile,
    REMOTE_SOURCE_KEY,
)


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _v3_manifest(*, name: str, description: str | None, version: str) -> dict:
    return {
        "schema": "promotion-template/v3",
        "version": version,
        "name": name,
        "description": description,
        "entry": "index.html",
        "format": "static-bundle",
        "capabilities": ["phone-pairing"],
        "runtime": "promotion-browser-bridge/v2",
        "requirements": {"pairingContract": "promotion-public-pairing/v1"},
        "components": {
            "contract": "account-link-elements/v1",
            "entry": "assets/account-link-elements.js",
        },
        "interactionProtection": "platform",
        "defaultLocale": "en",
        "supportedLocales": ["en"],
        "i18n": {
            "mode": "bundled",
            "path": "locales/{locale}.json",
            "fallbackLocale": "en",
        },
    }


def _verified_domain(admin_client: TestClient, hostname: str) -> dict:
    created = admin_client.post("/api/domains", json={"hostname": hostname})
    assert created.status_code == 201, created.text
    domain = created.json()["data"]["domain"]
    verified = admin_client.post(f"/api/domains/{domain['id']}/verify")
    assert verified.status_code == 200, verified.text
    return verified.json()["data"]["domain"]


class FakeRepositoryState:
    def __init__(self) -> None:
        self.scan_count = 0
        self.template = GitHubRemoteArtifact(
            sequence="0001",
            kind="template",
            slug="white-label-account-link",
            source="themes/white-label-account-link",
            manifest_path="themes/white-label-account-link/manifest.json",
            name="白标账号关联模板",
            description="仓库中的中文模板说明。",
            version="1.0.0",
            integration_key=None,
            integration_type=None,
            source_sha="template-source-v1",
            files=(),
        )
        self.integration = GitHubRemoteArtifact(
            sequence="0002",
            kind="integration",
            slug="promotion-integration-script-demo",
            source="examples/promotion-integration-script-demo",
            manifest_path="examples/promotion-integration-script-demo/integration.json",
            name="有序脚本集成",
            description="仓库中的中文集成说明。",
            version="1.0.0",
            integration_key="promotion-integration-script-demo",
            integration_type="script",
            source_sha="integration-source-v1",
            files=(),
        )

    def snapshot(self, kind: str | None) -> GitHubRepositorySnapshot:
        if kind == "template":
            artifacts = (self.template,)
        elif kind == "integration":
            artifacts = (self.integration,)
        else:
            artifacts = (self.template, self.integration)
        return GitHubRepositorySnapshot(
            repository="zaptel099/parloq-flow-template-kit",
            ref="main",
            commit_sha="a" * 40,
            artifacts=artifacts,
        )

    def archive(self, artifact: GitHubRemoteArtifact) -> bytes:
        if artifact.kind == "template":
            return _zip(
                {
                    "index.html": '<html><head></head><body>Repository template<script src="assets/account-link-elements.js"></script></body></html>',
                    "manifest.json": json.dumps(
                        _v3_manifest(
                            name=artifact.name,
                            description=artifact.description,
                            version=artifact.version,
                        ),
                        ensure_ascii=False,
                    ),
                    "assets/account-link-elements.js": "window.repositoryComponents = true;",
                    "locales/en.json": "{}",
                }
            )
        return _zip(
            {
                "integration.json": json.dumps(
                    {
                        "schemaVersion": 1,
                        "type": "script",
                        "version": artifact.version,
                        "integrationKey": artifact.integration_key,
                        "name": artifact.name,
                        "description": artifact.description,
                        "entry": "runtime.js",
                    },
                    ensure_ascii=False,
                ),
                "runtime.js": f"window.repositoryVersion = '{artifact.version}';",
            }
        )


class FakeRepositoryClient:
    def __init__(self, state: FakeRepositoryState) -> None:
        self.state = state
        self.catalog_path = "artifacts/catalog.json"

    def scan(self, *, kind: str | None):
        self.state.scan_count += 1
        return self.state.snapshot(kind)

    def archive_artifact(self, artifact: GitHubRemoteArtifact) -> bytes:
        return self.state.archive(artifact)

    def close(self) -> None:
        pass


def _install_repository_fakes(monkeypatch, state: FakeRepositoryState) -> None:
    monkeypatch.setattr(
        github_repository_service,
        "_configured_github_repository",
        lambda _db: (
            object(),
            "zaptel099/parloq-flow-template-kit",
            "main",
            "artifacts/catalog.json",
        ),
    )
    monkeypatch.setattr(
        github_repository_service,
        "configured_github_repository_client",
        lambda _db: FakeRepositoryClient(state),
    )
    monkeypatch.setattr(
        promotion_router,
        "configured_github_repository_client",
        lambda _db: FakeRepositoryClient(state),
    )
    monkeypatch.setattr(
        integration_router,
        "configured_github_repository_client",
        lambda _db: FakeRepositoryClient(state),
    )


def test_github_client_reads_catalog_and_source_directory_without_release_zip() -> None:
    contents = {
        "catalog": json.dumps(
            {
                "schemaVersion": 1,
                "artifacts": [
                    {
                        "sequence": "0001",
                        "kind": "template",
                        "slug": "repository-template",
                        "source": "themes/repository-template",
                        "manifest": "manifest.json",
                    },
                    {
                        "sequence": "0001",
                        "kind": "integration",
                        "slug": "repository-integration",
                        "source": "integrations/repository-integration",
                        "manifest": "integration.json",
                    }
                ],
            }
        ).encode(),
        "manifest": json.dumps(
            _v3_manifest(
                name="仓库模板",
                description="直接读取源码目录。",
                version="1.0.0",
            ),
            ensure_ascii=False,
        ).encode(),
        "index": b'<html><body>repository<script src="assets/account-link-elements.js"></script></body></html>',
        "components": b"window.repositoryComponents = true;",
        "locale": b"{}",
        "readme": b"not part of the imported template",
        "integration-manifest": json.dumps(
            {
                "schemaVersion": 1,
                "type": "script",
                "version": "1.0.0",
                "integrationKey": "repository-integration",
                "name": "仓库集成",
                "description": "与模板共用编号空间中的数字。",
                "entry": "runtime.js",
            },
            ensure_ascii=False,
        ).encode(),
        "integration-runtime": b"window.repositoryIntegration = true;",
    }
    paths = {
        "artifacts/catalog.json": "catalog",
        "themes/repository-template/manifest.json": "manifest",
        "themes/repository-template/index.html": "index",
        "themes/repository-template/assets/account-link-elements.js": "components",
        "themes/repository-template/locales/en.json": "locale",
        "themes/repository-template/README.md": "readme",
        "integrations/repository-integration/integration.json": "integration-manifest",
        "integrations/repository-integration/runtime.js": "integration-runtime",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/commits/" in request.url.path:
            return httpx.Response(
                200,
                json={"sha": "c" * 40, "commit": {"tree": {"sha": "t" * 40}}},
            )
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {
                            "path": path,
                            "type": "blob",
                            "sha": key,
                            "size": len(contents[key]),
                        }
                        for path, key in paths.items()
                    ],
                },
            )
        if "/git/blobs/" in request.url.path:
            key = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(contents[key]).decode(),
                },
            )
        return httpx.Response(404)

    http = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    try:
        client = GitHubRepositoryClient(
            "private-token",
            repository="owner/private-repository",
            client=http,
        )
        snapshot = client.scan(kind=None)
        assert {(value.kind, value.sequence) for value in snapshot.artifacts} == {
            ("template", "0001"),
            ("integration", "0001"),
        }
        artifact = next(value for value in snapshot.artifacts if value.kind == "template")
        assert artifact.name == "仓库模板"
        assert [file.path for file in artifact.files] == [
            "themes/repository-template/manifest.json",
            "themes/repository-template/index.html",
            "themes/repository-template/assets/account-link-elements.js",
            "themes/repository-template/locales/en.json",
        ]
        archive_bytes = client.archive_artifact(artifact)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert sorted(archive.namelist()) == [
                "assets/account-link-elements.js",
                "index.html",
                "locales/en.json",
                "manifest.json",
            ]
    finally:
        http.close()


def test_repository_archive_allows_large_video_but_keeps_other_files_at_five_mb(
    monkeypatch,
) -> None:
    client = GitHubRepositoryClient(
        "private-token",
        repository="owner/private-repository",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(404))),
    )
    video = GitHubTreeFile(
        path="themes/video/assets/reveal.mp4",
        sha="video",
        size=10 * 1024 * 1024,
    )
    artifact = GitHubRemoteArtifact(
        sequence="0006",
        kind="template",
        slug="video",
        source="themes/video",
        manifest_path="themes/video/manifest.json",
        name="Video",
        description=None,
        version="1",
        integration_key=None,
        integration_type=None,
        source_sha="source",
        files=(video,),
    )
    monkeypatch.setattr(client, "_blob_bytes", lambda _file, *, max_bytes: b"video")
    try:
        assert client.archive_artifact(artifact)
        regular = replace(
            artifact,
            files=(replace(video, path="themes/video/assets/app.js", size=6 * 1024 * 1024),),
        )
        with pytest.raises(
            GitHubRepositoryArtifactValidationError,
            match="仓库文件超过 5MB",
        ):
            client.archive_artifact(regular)
        oversized_video = replace(
            artifact,
            files=(replace(video, size=51 * 1024 * 1024),),
        )
        with pytest.raises(
            GitHubRepositoryArtifactValidationError,
            match="视频文件超过 50MB",
        ):
            client.archive_artifact(oversized_video)
    finally:
        client._client.close()


def test_repository_artifact_validation_error_maps_to_422() -> None:
    error = GitHubRepositoryArtifactValidationError("仓库文件超过限制")
    assert promotion_router._repository_http_error(error).status_code == 422
    assert integration_router._repository_http_error(error).status_code == 422


def test_repository_template_can_be_added_and_updated_without_overwriting_name(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    state = FakeRepositoryState()
    _install_repository_fakes(monkeypatch, state)

    remote = admin_client.get("/api/promotion/templates/repository")
    assert remote.status_code == 200, remote.text
    assert remote.json()["data"]["rows"][0]["localStatus"] == "new"
    assert remote.json()["data"]["refreshedAt"]
    assert remote.json()["data"]["cacheHit"] is False
    assert state.scan_count == 1
    cached = admin_client.get("/api/promotion/templates/repository")
    assert cached.status_code == 200, cached.text
    assert cached.json()["data"]["cacheHit"] is True
    assert state.scan_count == 1

    imported = admin_client.post("/api/promotion/templates/repository/0001/import")
    assert imported.status_code == 200, imported.text
    assert imported.json()["data"]["action"] == "added"
    template = imported.json()["data"]["template"]
    assert template["name"] == "白标账号关联模板"
    assert template["manifest"][REMOTE_SOURCE_KEY]["sequence"] == "0001"

    current = admin_client.get("/api/promotion/templates/repository")
    assert current.json()["data"]["rows"][0]["localStatus"] == "current"
    renamed = admin_client.post(
        f"/api/promotion/templates/{template['id']}/edit",
        data={
            "name": "本地手动名称",
            "description": "本地模板说明",
            "status": "active",
            "integrationIds": "[]",
        },
    )
    assert renamed.status_code == 200, renamed.text

    state.template = replace(
        state.template,
        version="2.0.0",
        source_sha="template-source-v2",
    )
    available = admin_client.post("/api/promotion/templates/repository/refresh")
    assert available.json()["data"]["cacheHit"] is False
    assert available.json()["data"]["rows"][0]["localStatus"] == "update"
    local = admin_client.get("/api/promotion/templates")
    assert local.status_code == 200, local.text
    local_row = next(
        row for row in local.json()["data"]["rows"] if row["id"] == template["id"]
    )
    source = local_row["repositorySource"]
    assert source["sequence"] == "0001"
    assert source["localStatus"] == "update"
    assert source["remoteVersion"] == "2.0.0"
    updated = admin_client.post("/api/promotion/templates/repository/0001/import")
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["action"] == "updated"
    assert updated.json()["data"]["template"]["version"] == "2.0.0"
    assert updated.json()["data"]["template"]["name"] == "本地手动名称"

    state.template = replace(
        state.template,
        source_sha="template-source-v2-edited-without-version-bump",
    )
    conflict = admin_client.post("/api/promotion/templates/repository/refresh")
    assert conflict.json()["data"]["rows"][0]["localStatus"] == "conflict"
    rejected = admin_client.post("/api/promotion/templates/repository/0001/import")
    assert rejected.status_code == 409, rejected.text
    assert "version" in rejected.json()["detail"]


def test_repository_integration_requires_domain_then_updates_in_place(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    state = FakeRepositoryState()
    _install_repository_fakes(monkeypatch, state)
    domain = _verified_domain(admin_client, "repository-integration.test")

    remote = admin_client.get("/api/promotion/integrations/repository")
    assert remote.status_code == 200, remote.text
    assert remote.json()["data"]["rows"][0]["localStatus"] == "new"

    missing_domain = admin_client.post(
        "/api/promotion/integrations/repository/0002/import",
        json={},
    )
    assert missing_domain.status_code == 422, missing_domain.text
    assert missing_domain.json()["detail"] == "请选择集成源域名"

    imported = admin_client.post(
        "/api/promotion/integrations/repository/0002/import",
        json={"domainId": domain["id"], "enabled": True},
    )
    assert imported.status_code == 200, imported.text
    integration = imported.json()["data"]["integration"]
    assert integration["name"] == "有序脚本集成"
    assert integration["domainId"] == domain["id"]

    renamed = admin_client.post(
        f"/api/promotion/integrations/{integration['id']}/edit",
        data={
            "integrationKey": integration["integrationKey"],
            "name": "本地手动集成名称",
            "description": "本地集成说明",
            "domainId": domain["id"],
            "enabled": "true",
        },
    )
    assert renamed.status_code == 200, renamed.text
    state.integration = replace(
        state.integration,
        sequence="0001",
        version="2.0.0",
        source_sha="integration-source-v2",
    )
    available = admin_client.post("/api/promotion/integrations/repository/refresh")
    assert available.json()["data"]["rows"][0]["localStatus"] == "update"
    local = admin_client.get("/api/promotion/integrations")
    assert local.status_code == 200, local.text
    source = local.json()["data"]["rows"][0]["repositorySource"]
    assert source["sequence"] == "0001"
    assert source["localStatus"] == "update"
    assert source["remoteVersion"] == "2.0.0"
    updated = admin_client.post(
        "/api/promotion/integrations/repository/0001/import",
        json={},
    )
    assert updated.status_code == 200, updated.text
    result = updated.json()["data"]["integration"]
    assert result["version"] == "2.0.0"
    assert result["name"] == "本地手动集成名称"
    assert result["domainId"] == domain["id"]
