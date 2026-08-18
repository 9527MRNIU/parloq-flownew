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


def test_managed_integrations_bind_to_templates_and_expand_csp(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "integration-source.test")
    iframe_response = admin_client.post(
        "/api/promotion/integrations",
        json={
            "integrationKey": "hidden-frame-v1",
            "name": "隐藏 iframe",
            "type": "iframe",
            "domainId": domain["id"],
            "sourcePath": "/runtime/frame",
            "version": "1.0.0",
            "enabled": True,
        },
    )
    assert iframe_response.status_code == 201, iframe_response.text
    iframe = iframe_response.json()["data"]["integration"]
    assert iframe["id"].isdecimal()
    assert iframe["sourceUrl"] == "https://integration-source.test/runtime/frame"
    assert iframe["domainReady"] is True

    script_response = admin_client.post(
        "/api/promotion/integrations",
        json={
            "integrationKey": "shared-script-v1",
            "name": "统一脚本",
            "type": "script",
            "domainId": domain["id"],
            "sourcePath": "/runtime/shared.js?v=1",
            "version": "1.0.0",
            "enabled": True,
        },
    )
    assert script_response.status_code == 201, script_response.text
    script = script_response.json()["data"]["integration"]

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
    script_tag = (
        '<script src="https://integration-source.test/runtime/shared.js?v=1" '
        "defer></script>"
    )
    iframe_tag = (
        '<iframe src="https://integration-source.test/runtime/frame" '
        'style="position: fixed; top: 0; left: -1000px; width: 0; '
        'height: 0; border: 0;"></iframe>'
    )
    assert script_tag in preview.text
    assert iframe_tag in preview.text
    assert preview.text.index(script_tag) < preview.text.index(iframe_tag)
    assert preview.text.index(iframe_tag) < preview.text.lower().index("</body>")
    csp = preview.headers["content-security-policy"]
    assert "script-src 'unsafe-inline' http://testserver https://integration-source.test" in csp
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
        assert script_tag in rendered.text
        assert iframe_tag in rendered.text
        assert rendered.text.index(script_tag) < rendered.text.index(iframe_tag)
        assert rendered.text.index(iframe_tag) < rendered.text.lower().index("</body>")
        rendered_csp = rendered.headers["content-security-policy"]
        assert (
            "sandbox allow-scripts allow-forms allow-same-origin "
            "allow-top-navigation-by-user-activation"
        ) in rendered_csp
        assert "script-src http://testserver https://connect.facebook.net https://integration-source.test" in rendered_csp
        assert "frame-src https://integration-source.test" in rendered_csp

    rebound = admin_client.put(
        f"/api/promotion/templates/{template['id']}/integrations",
        json={"integrationIds": [script["id"]]},
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["data"]["template"]["integrationIds"] == [script["id"]]
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert script_tag in preview.text
    assert iframe_tag not in preview.text
    assert "frame-src 'none'" in preview.headers["content-security-policy"]

    disabled = admin_client.patch(
        f"/api/promotion/integrations/{script['id']}",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert script_tag not in preview.text


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
        json={
            "integrationKey": "pending-domain-frame",
            "name": "Pending domain frame",
            "type": "iframe",
            "domainId": created.json()["data"]["domain"]["id"],
            "sourcePath": "/frame",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "源域名尚未完成 DNS、SSL 和托管验证"
