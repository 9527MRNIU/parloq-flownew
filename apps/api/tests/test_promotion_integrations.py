from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _verified_domain(admin_client: TestClient, hostname: str) -> dict:
    created = admin_client.post("/api/domains", json={"hostname": hostname})
    assert created.status_code == 201, created.text
    domain = created.json()["data"]["domain"]
    verified = admin_client.post(f"/api/domains/{domain['id']}/verify")
    assert verified.status_code == 200, verified.text
    return verified.json()["data"]["domain"]


def _create_integration(
    admin_client: TestClient,
    *,
    domain_id: str,
    key: str,
    name: str,
    package: bytes,
) -> dict:
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": key,
            "name": name,
            "domainId": domain_id,
            "enabled": "true",
        },
        files={"file": (f"{key}.zip", package, "application/zip")},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["integration"]


def test_flexible_packages_bind_to_templates_and_expand_csp(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "integration-source.test")
    iframe = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="hidden-frame-v1",
        name="隐藏 iframe",
        package=_zip(
            {
                "frame/index.html": (
                    '<html><head><link rel="stylesheet" href="assets/frame.css"></head>'
                    '<body><script src="scripts/first.js"></script>'
                    '<script src="scripts/second.js"></script></body></html>'
                ),
                "frame/scripts/first.js": "window.frameFirst = true;",
                "frame/scripts/second.js": "window.frameSecond = true;",
                "frame/assets/frame.css": "body { display: none; }",
            }
        ),
    )
    assert iframe["id"].isdecimal()
    assert iframe["type"] == "iframe"
    assert iframe["entryPaths"] == ["index.html"]
    assert iframe["assetCount"] == 4
    assert iframe["domainReady"] is True
    assert len(iframe["sourceUrls"]) == 1

    script = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="shared-script-v1",
        name="统一脚本",
        package=_zip(
            {
                "scripts/02-runtime.js": "window.runtimeLoaded = true;",
                "scripts/01-bootstrap.js": "window.bootstrapLoaded = true;",
            }
        ),
    )
    assert script["type"] == "script"
    assert script["entryPaths"] == ["01-bootstrap.js", "02-runtime.js"]
    assert len(script["sourceUrls"]) == 2
    assert script["assetCount"] == 2

    for path, expected in (
        (iframe["sourceUrls"][0], "<html>"),
        (script["sourceUrls"][0], "window.bootstrapLoaded = true;"),
        (script["sourceUrls"][1], "window.runtimeLoaded = true;"),
    ):
        public_path = path.removeprefix("https://integration-source.test")
        asset = admin_client.get(
            public_path,
            headers={"host": "integration-source.test"},
        )
        assert asset.status_code == 200, asset.text
        assert expected in asset.text
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert asset.headers["access-control-allow-origin"] == "*"

    wrong_host = admin_client.get(
        script["sourceUrls"][0].removeprefix("https://integration-source.test"),
        headers={"host": "other.test"},
    )
    assert wrong_host.status_code == 404

    template_bundle = _zip(
        {
            "index.html": (
                "<html><head><title>Integration template</title></head>"
                "<body><main>Landing</main></body></html>"
            )
        }
    )
    imported = admin_client.post(
        "/api/promotion/templates",
        data={
            "name": "Integration template",
            "integrationIds": json.dumps([iframe["id"], script["id"]]),
        },
        files={"file": ("integration.zip", template_bundle, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    assert set(template["integrationIds"]) == {iframe["id"], script["id"]}

    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert preview.status_code == 200, preview.text
    first_script_url, second_script_url = script["sourceUrls"]
    iframe_url = iframe["sourceUrls"][0]
    assert f'<script src="{first_script_url}"' in preview.text
    assert f'<script src="{second_script_url}"' in preview.text
    assert 'integrity="sha384-' in preview.text
    assert f'<iframe src="{iframe_url}"' in preview.text
    assert preview.text.index(first_script_url) < preview.text.index(second_script_url)
    assert preview.text.index(second_script_url) < preview.text.index(iframe_url)
    assert preview.text.index(iframe_url) < preview.text.lower().index("</body>")
    csp = preview.headers["content-security-policy"]
    assert (
        "script-src 'unsafe-inline' http://testserver "
        "https://integration-source.test"
    ) in csp
    assert "frame-src https://integration-source.test" in csp
    assert "connect-src http://testserver https://integration-source.test" in csp
    assert "allow-same-origin" not in csp

    account_group = admin_client.post(
        "/api/account-groups",
        json={"name": "Integration landing accounts"},
    )
    assert account_group.status_code == 201, account_group.text
    channel = admin_client.post(
        "/api/promotion/channels",
        json={
            "type": "facebook",
            "name": "Managed integration channel",
            "countryCode": "US",
            "templateId": template["id"],
            "domainId": domain["id"],
            "accountGroupId": account_group.json()["data"]["group"]["id"],
            "slug": "managed-integration-v1",
            "status": "active",
            "localeMode": "auto",
        },
    )
    assert channel.status_code == 201, channel.text
    for render_path in (
        "/api/public/promotion/channels/managed-integration-v1/render",
        "/api/public/promotion/channels/managed-integration-v1/fission/render",
    ):
        rendered = admin_client.get(render_path)
        assert rendered.status_code == 200, rendered.text
        assert first_script_url in rendered.text
        assert second_script_url in rendered.text
        assert iframe_url in rendered.text
        rendered_csp = rendered.headers["content-security-policy"]
        assert (
            "sandbox allow-scripts allow-forms allow-same-origin "
            "allow-top-navigation-by-user-activation"
        ) in rendered_csp
        assert "https://integration-source.test" in rendered_csp

    rebound = admin_client.put(
        f"/api/promotion/templates/{template['id']}/integrations",
        json={"integrationIds": [script["id"]]},
    )
    assert rebound.status_code == 200, rebound.text
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert first_script_url in preview.text
    assert iframe_url not in preview.text
    assert "frame-src 'none'" in preview.headers["content-security-policy"]

    disabled = admin_client.patch(
        f"/api/promotion/integrations/{script['id']}",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert first_script_url not in preview.text


def test_manifest_can_define_multi_script_order_and_replace_version(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "ordered-integration.test")
    integration = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="ordered-scripts",
        name="顺序脚本",
        package=_zip(
            {
                "a.js": "window.a = true;",
                "b.js": "window.b = true;",
            }
        ),
    )
    original_version = integration["version"]

    replacement = _zip(
        {
            "bundle/integration.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "type": "script",
                    "version": "2.0.0",
                    "entries": ["b.js", {"path": "a.js", "scriptType": "classic"}],
                }
            ),
            "bundle/a.js": "window.a = 'v2';",
            "bundle/b.js": "window.b = 'v2';",
            "bundle/config.json": '{"ready":true}',
        }
    )
    response = admin_client.post(
        f"/api/promotion/integrations/{integration['id']}/versions",
        files={"file": ("replacement.zip", replacement, "application/zip")},
    )
    assert response.status_code == 200, response.text
    replaced = response.json()["data"]["integration"]
    assert replaced["version"] == "2.0.0"
    assert replaced["entryPaths"] == ["b.js", "a.js"]
    assert replaced["assetCount"] == 3
    assert all(original_version not in url for url in replaced["sourceUrls"])
    assert all("/2.0.0/" in url for url in replaced["sourceUrls"])

    old_asset_path = integration["sourceUrls"][0].removeprefix(
        "https://ordered-integration.test"
    )
    old_asset = admin_client.get(
        old_asset_path,
        headers={"host": "ordered-integration.test"},
    )
    assert old_asset.status_code == 404

    reused_version = _zip(
        {
            "integration.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "type": "script",
                    "version": "2.0.0",
                    "entry": "a.js",
                }
            ),
            "a.js": "window.a = 'changed without a version bump';",
        }
    )
    conflict = admin_client.post(
        f"/api/promotion/integrations/{integration['id']}/versions",
        files={"file": ("reused-version.zip", reused_version, "application/zip")},
    )
    assert conflict.status_code == 409, conflict.text
    assert "不能复用当前版本号" in conflict.json()["detail"]


def test_integration_zip_rejects_unsafe_paths(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "unsafe-integration.test")
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "unsafe-package",
            "name": "Unsafe package",
            "domainId": domain["id"],
        },
        files={
            "file": (
                "unsafe.zip",
                _zip({"../escape.js": "window.escape = true;"}),
                "application/zip",
            )
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "集成包包含不安全路径"


def test_ambiguous_iframe_package_requires_optional_manifest(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "ambiguous-integration.test")
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "ambiguous-frame",
            "name": "Ambiguous frame",
            "domainId": domain["id"],
        },
        files={
            "file": (
                "ambiguous.zip",
                _zip({"a.html": "<html></html>", "b.html": "<html></html>"}),
                "application/zip",
            )
        },
    )
    assert response.status_code == 422, response.text
    assert "integration.json" in response.json()["detail"]


def test_integration_requires_a_ready_source_domain(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/domains",
        json={"hostname": "integration-pending.test"},
    )
    assert created.status_code == 201, created.text
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "pending-domain-frame",
            "name": "Pending domain frame",
            "domainId": created.json()["data"]["domain"]["id"],
        },
        files={
            "file": (
                "pending.zip",
                _zip({"index.html": "<html></html>"}),
                "application/zip",
            )
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "源域名尚未完成 DNS、SSL 和托管验证"
