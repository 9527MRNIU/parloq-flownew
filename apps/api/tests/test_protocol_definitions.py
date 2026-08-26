from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.protocol_catalog import is_prerelease_version
from app.services.protocol_builds import (
    ProtocolBuildResult,
    process_next_protocol_build,
)


def test_protocol_version_category_uses_semver_prerelease_suffix() -> None:
    assert is_prerelease_version("6.7.24") is False
    assert is_prerelease_version("6.7.24+build.1") is False
    assert is_prerelease_version("7.0.0-rc14") is True
    assert is_prerelease_version("7.0.0-rc.9") is True
    assert is_prerelease_version("7.0.0-beta.1") is True


def test_protocol_definitions_separate_versions_from_nodes(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.routers.protocol_definitions.npm_version_summary",
        lambda _package_name: {
            "latestStable": "6.7.24",
            "latestPreview": "7.0.0-rc.14",
            "checkedAt": "2026-08-24T00:00:00+00:00",
            "error": None,
        },
    )
    monkeypatch.setattr(
        "app.routers.protocol_definitions.npm_package_catalog",
        lambda _package_name: {
            "latest": "7.0.0-rc.14",
            "latestStable": "6.7.24",
            "latestPreview": "7.0.0-rc.14",
            "tags": {
                "latest": "7.0.0-rc.14",
                "legacy": "6.7.24",
            },
            "versions": ["7.0.0-rc.14", "6.7.24"],
            "stableVersions": ["6.7.24"],
            "previewVersions": ["7.0.0-rc.14"],
            "checkedAt": "2026-08-24T00:00:00+00:00",
            "error": None,
        },
    )

    listed = admin_client.get("/api/protocol-definitions")
    assert listed.status_code == 200, listed.text
    builtin = listed.json()["data"]["rows"][0]
    assert builtin["name"] == "Baileys Web协议"
    assert builtin["version"] == "6.7.24"
    assert builtin["buildStatus"] == "ready"
    assert builtin["versionCategory"] == "stable"
    assert builtin["remoteLatestVersion"] == "6.7.24"
    assert builtin["nodeCount"] >= 0

    options = admin_client.get("/api/protocol-definitions/options")
    assert options.status_code == 200, options.text
    assert [row["id"] for row in options.json()["data"]["rows"]] == [
        builtin["id"]
    ]

    available_versions = admin_client.get(
        "/api/protocol-definitions/available-versions",
        params={"packageName": "@whiskeysockets/baileys"},
    )
    assert available_versions.status_code == 200, available_versions.text
    assert available_versions.json()["data"]["rows"] == [
        {
            "version": "6.7.24",
            "category": "stable",
            "tags": ["legacy"],
        },
        {
            "version": "7.0.0-rc.14",
            "category": "preview",
            "tags": ["latest"],
        },
    ]
    assert available_versions.json()["data"]["latestStable"] == "6.7.24"
    assert (
        available_versions.json()["data"]["latestPreview"]
        == "7.0.0-rc.14"
    )

    invalid_version = admin_client.post(
        "/api/protocol-definitions",
        json={
            "name": "不存在的协议版本",
            "adapterKey": "baileys",
            "repositoryUrl": "https://github.com/WhiskeySockets/Baileys",
            "packageName": "@whiskeysockets/baileys",
            "version": "99.99.99",
        },
    )
    assert invalid_version.status_code == 422
    assert "远程版本列表" in invalid_version.json()["detail"]

    created = admin_client.post(
        "/api/protocol-definitions",
        json={
            "name": "Baileys Web协议候选版",
            "adapterKey": "baileys",
            "repositoryUrl": "https://github.com/WhiskeySockets/Baileys",
            "packageName": "@whiskeysockets/baileys",
            "version": "7.0.0-rc.14",
        },
    )
    assert created.status_code == 201, created.text
    candidate = created.json()["data"]["protocol"]
    assert candidate["buildStatus"] == "pending"
    assert candidate["runtimeInstalled"] is False
    assert candidate["latestBuild"]["status"] == "queued"
    assert candidate["versionCategory"] == "preview"
    assert candidate["remoteLatestVersion"] == "7.0.0-rc.14"

    sorted_definitions = admin_client.get(
        "/api/protocol-definitions",
        params={"sortBy": "version", "sortOrder": "desc", "pageSize": 1},
    )
    assert sorted_definitions.status_code == 200, sorted_definitions.text
    assert sorted_definitions.json()["data"]["rows"][0]["id"] == candidate["id"]
    filtered_definitions = admin_client.get(
        "/api/protocol-definitions",
        params={"keyword": candidate["id"]},
    )
    assert filtered_definitions.status_code == 200, filtered_definitions.text
    assert [
        row["id"] for row in filtered_definitions.json()["data"]["rows"]
    ] == [candidate["id"]]

    unavailable = admin_client.post(
        "/api/protocol-nodes",
        json={
            "name": "候选版测试节点",
            "protocolDefinitionId": candidate["id"],
        },
    )
    assert unavailable.status_code == 409
    assert "尚未构建完成" in unavailable.json()["detail"]

    class _Builder:
        def build(self, **_kwargs) -> ProtocolBuildResult:
            return ProtocolBuildResult(
                artifact_digest="a" * 64,
                artifact_integrity="sha512-test",
                log_excerpt="contract smoke test passed",
            )

    assert process_next_protocol_build(_Builder()) is True
    refreshed = admin_client.get("/api/protocol-definitions")
    ready_candidate = next(
        row
        for row in refreshed.json()["data"]["rows"]
        if row["id"] == candidate["id"]
    )
    assert ready_candidate["buildStatus"] == "ready"
    assert ready_candidate["runtimeInstalled"] is True
    assert ready_candidate["latestBuild"]["status"] == "succeeded"

    created_node = admin_client.post(
        "/api/protocol-nodes",
        json={
            "name": "候选版测试节点",
            "protocolDefinitionId": candidate["id"],
        },
    )
    assert created_node.status_code == 201, created_node.text
    node_id = created_node.json()["data"]["protocol"]["id"]
    in_use = admin_client.delete(
        f"/api/protocol-definitions/{candidate['id']}"
    )
    assert in_use.status_code == 409
    assert admin_client.delete(f"/api/protocol-nodes/{node_id}").status_code == 200
    deleted = admin_client.delete(
        f"/api/protocol-definitions/{candidate['id']}"
    )
    assert deleted.status_code == 200, deleted.text
