from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.business_schemas import PublicEvent
from app.validation import PROMOTION_INTEGRATION_EVENT_MAX_BYTES


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
        if expected == "<html>":
            assert "promotion-integration-frame.js" not in asset.text

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


def test_iframe_manifest_can_use_ordered_javascript_entries(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "javascript-frame.test")
    integration = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="javascript-frame-v1",
        name="全 JavaScript iframe",
        package=_zip(
            {
                "integration.json": json.dumps(
                    {
                        "schemaVersion": 1,
                        "type": "iframe",
                        "version": "3.1.0",
                        "entries": ["ds_net.js", "ds_net_native.mjs"],
                        "feedback": {
                            "enabled": True,
                            "events": ["ip_sync", "device_activate"],
                        },
                    }
                ),
                "ds_net.js": "window.loadOrder = ['web'];",
                "ds_net_native.mjs": "window.loadOrder.push('native');",
            }
        ),
    )

    assert integration["type"] == "iframe"
    assert integration["version"] == "3.1.0"
    assert integration["entryPaths"] == ["ds_net.js", "ds_net_native.mjs"]
    assert integration["entrypoints"] == [
        {"path": "ds_net.js", "scriptType": "classic"},
        {"path": "ds_net_native.mjs", "scriptType": "module"},
    ]
    assert integration["feedbackEvents"] == [
        "page_view",
        "visit_end",
        "ip_sync",
        "device_activate",
    ]
    assert len(integration["sourceUrls"]) == 1
    wrapper_url = integration["sourceUrls"][0]
    assert wrapper_url.endswith("/3.1.0/__parloq_iframe__.html")

    wrapper_path = wrapper_url.removeprefix("https://javascript-frame.test")
    wrapper = admin_client.get(
        wrapper_path,
        headers={"host": "javascript-frame.test"},
    )
    assert wrapper.status_code == 200, wrapper.text
    assert wrapper.headers["content-type"].startswith("text/html")
    assert wrapper.headers["cache-control"] == "public, max-age=31536000, immutable"
    runtime_url = "/api/public/promotion/integrations/runtime.js"
    asset_base = wrapper_url.rsplit("/", 1)[0]
    first_url = f"{asset_base}/ds_net.js"
    second_url = f"{asset_base}/ds_net_native.mjs"
    assert f'<script src="{first_url}" defer></script>' in wrapper.text
    assert f'<script src="{second_url}" type="module"></script>' in wrapper.text
    assert wrapper.text.index(runtime_url) < wrapper.text.index(first_url)
    assert wrapper.text.index(first_url) < wrapper.text.index(second_url)
    assert f'data-integration-id="{integration["id"]}"' in wrapper.text

    first_asset = admin_client.get(
        first_url.removeprefix("https://javascript-frame.test"),
        headers={"host": "javascript-frame.test"},
    )
    assert first_asset.status_code == 200, first_asset.text
    assert first_asset.text == "window.loadOrder = ['web'];"

    wrong_host = admin_client.get(wrapper_path, headers={"host": "other.test"})
    assert wrong_host.status_code == 404
    wrong_version = admin_client.get(
        wrapper_path.replace("/3.1.0/", "/3.0.0/"),
        headers={"host": "javascript-frame.test"},
    )
    assert wrong_version.status_code == 404

    imported = admin_client.post(
        "/api/promotion/templates",
        data={
            "name": "JavaScript iframe template",
            "integrationIds": json.dumps([integration["id"]]),
        },
        files={
            "file": (
                "javascript-frame-template.zip",
                _zip({"index.html": "<html><body>Landing</body></html>"}),
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.text.count(wrapper_url) == 1
    assert first_url not in preview.text
    assert "frame-src https://javascript-frame.test" in preview.headers[
        "content-security-policy"
    ]


def test_iframe_feedback_uses_an_independent_runtime_and_persists_events(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    domain = _verified_domain(admin_client, "integration-feedback.test")
    integration = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="feedback-frame",
        name="反馈 iframe",
        package=_zip(
            {
                "integration.json": json.dumps(
                    {
                        "schemaVersion": 1,
                        "type": "iframe",
                        "version": "1.0.0",
                        "entry": "index.html",
                        "feedback": {
                            "enabled": True,
                            "events": ["ready", "completed", "failed"],
                        },
                    }
                ),
                "index.html": (
                    "<html><head><title>Feedback</title></head>"
                    "<body><script src='frame.js'></script></body></html>"
                ),
                "frame.js": (
                    "window.PromotionIntegrationBridge?.report('ready', {ok:true});"
                ),
            }
        ),
    )
    assert integration["feedbackEnabled"] is True
    assert integration["feedbackEvents"] == [
        "page_view",
        "visit_end",
        "ready",
        "completed",
        "failed",
    ]

    entry_path = integration["sourceUrls"][0].removeprefix(
        "https://integration-feedback.test"
    )
    entry = admin_client.get(
        entry_path,
        headers={"host": "integration-feedback.test"},
    )
    assert entry.status_code == 200, entry.text
    assert "/api/public/promotion/integrations/runtime.js" in entry.text
    assert f'data-integration-id="{integration["id"]}"' in entry.text

    imported = admin_client.post(
        "/api/promotion/templates",
        data={
            "name": "Feedback template",
            "integrationIds": json.dumps([integration["id"]]),
        },
        files={
            "file": (
                "feedback-template.zip",
                _zip({"index.html": "<html><head></head><body>Landing</body></html>"}),
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    account_group = admin_client.post(
        "/api/account-groups", json={"name": "Feedback integration accounts"}
    )
    assert account_group.status_code == 201, account_group.text
    channel_response = admin_client.post(
        "/api/promotion/channels",
        json={
            "type": "facebook",
            "name": "Feedback channel",
            "countryCode": "US",
            "templateId": template["id"],
            "domainId": domain["id"],
            "accountGroupId": account_group.json()["data"]["group"]["id"],
            "slug": "feedback-channel-v1",
            "status": "active",
            "localeMode": "auto",
        },
    )
    assert channel_response.status_code == 201, channel_response.text
    channel = channel_response.json()["data"]["channel"]

    rendered = admin_client.get(
        "/api/public/promotion/channels/feedback-channel-v1/render"
    )
    assert rendered.status_code == 200, rendered.text
    token_match = re.search(r"#parloqEmbedToken=([^\"]+)", rendered.text)
    assert token_match is not None
    token = unquote(token_match.group(1))

    runtime = admin_client.get(
        f"/api/public/promotion/integrations/{integration['id']}/runtime",
        headers={
            "host": "integration-feedback.test",
            "authorization": f"Bearer {token}",
        },
    )
    assert runtime.status_code == 200, runtime.text
    runtime_data = runtime.json()["data"]
    assert runtime_data["integration"]["id"] == integration["id"]
    assert runtime_data["channel"]["id"] == channel["id"]
    assert runtime_data["template"]["id"] == template["id"]
    assert runtime_data["events"] == integration["feedbackEvents"]
    assert runtime_data["fingerprintEnabled"] is True
    assert runtime.headers["cache-control"] == "no-store"

    event_payload = {
        "eventType": "completed",
        "idempotencyKey": "feedback-event-0001",
        "visitorId": "visitor-feedback-0001",
        "sessionToken": runtime_data["sessionToken"],
        "metadata": {"result": "ok", "count": 2},
    }
    event = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={"host": "integration-feedback.test"},
        json=event_payload,
    )
    assert event.status_code == 201, event.text
    assert event.json()["data"]["duplicate"] is False
    event_id = event.json()["data"]["eventId"]
    duplicate = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={"host": "integration-feedback.test"},
        json=event_payload,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["data"]["duplicate"] is True

    from app.services.promotion_event_rate_limits import (
        PromotionEventRateLimitDecision,
    )

    with monkeypatch.context() as context:
        context.setattr(
            "app.routers.promotion_integrations.consume_promotion_event_rate_limits",
            lambda *_args, **_kwargs: PromotionEventRateLimitDecision(
                allowed=False,
                retry_after_seconds=23,
                policy_key="ipReports",
                limit=1,
            ),
        )
        limited = admin_client.post(
            f"/api/public/promotion/integrations/{integration['id']}/events",
            headers={"host": "integration-feedback.test"},
            json={
                **event_payload,
                "idempotencyKey": "feedback-rate-limited-0001",
            },
        )
    assert limited.status_code == 429, limited.text
    assert limited.headers["retry-after"] == "23"
    assert limited.json()["error"]["code"] == "report_rate_limited"

    undeclared = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={"host": "integration-feedback.test"},
        json={**event_payload, "eventType": "not_declared", "idempotencyKey": "bad-event-0001"},
    )
    assert undeclared.status_code == 422, undeclared.text

    metadata_limit = 1024 * 1024
    boundary_metadata = {"blob": "x" * (metadata_limit - len(b'{"blob":""}'))}
    assert len(
        json.dumps(
            boundary_metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) == metadata_limit
    boundary = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={"host": "integration-feedback.test"},
        json={
            **event_payload,
            "idempotencyKey": "feedback-boundary-0001",
            "metadata": boundary_metadata,
        },
    )
    assert boundary.status_code == 201, boundary.text

    metadata_too_large = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={"host": "integration-feedback.test"},
        json={
            **event_payload,
            "idempotencyKey": "feedback-metadata-large-0001",
            "metadata": {"blob": boundary_metadata["blob"] + "x"},
        },
    )
    assert metadata_too_large.status_code == 422, metadata_too_large.text

    envelope_too_large = admin_client.post(
        f"/api/public/promotion/integrations/{integration['id']}/events",
        headers={
            "host": "integration-feedback.test",
            "content-type": "text/plain;charset=UTF-8",
        },
        content=b"x" * (PROMOTION_INTEGRATION_EVENT_MAX_BYTES + 1),
    )
    assert envelope_too_large.status_code == 413, envelope_too_large.text

    events = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}/events"
    )
    assert events.status_code == 200, events.text
    event_data = events.json()["data"]
    assert event_data["total"] == 2
    assert event_data["summary"] == [{"eventType": "completed", "count": 2}]
    event_row = next(row for row in event_data["rows"] if row["id"] == event_id)
    assert event_row["channelId"] == channel["id"]
    assert "metadata" not in event_row
    encoded_metadata = b'{"count":2,"result":"ok"}'
    assert event_row["metadataBytes"] == len(encoded_metadata)
    assert event_row["metadataSha256"] == hashlib.sha256(encoded_metadata).hexdigest()

    event_detail = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}/events/{event_id}"
    )
    assert event_detail.status_code == 200, event_detail.text
    detail_data = event_detail.json()["data"]["event"]
    assert detail_data["metadata"] == {"result": "ok", "count": 2}
    assert detail_data["metadataBytes"] == len(encoded_metadata)
    assert detail_data["metadataSha256"] == hashlib.sha256(encoded_metadata).hexdigest()

    boundary_event_id = boundary.json()["data"]["eventId"]
    boundary_detail = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}/events/{boundary_event_id}"
    )
    assert boundary_detail.status_code == 200, boundary_detail.text
    assert boundary_detail.json()["data"]["event"]["metadata"] == boundary_metadata

    refreshed = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}"
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["data"]["integration"]["eventCount"] == 2


def test_public_event_metadata_limit_remains_4_kib() -> None:
    with pytest.raises(ValidationError, match="JSON 内容过大"):
        PublicEvent(
            idempotencyKey="public-event-0001",
            visitorId="public-visitor-0001",
            metadata={"blob": "x" * 4096},
        )


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


def test_iframe_manifest_rejects_mixed_html_and_javascript_entries(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "mixed-frame.test")
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "mixed-frame",
            "name": "Mixed frame",
            "domainId": domain["id"],
        },
        files={
            "file": (
                "mixed-frame.zip",
                _zip(
                    {
                        "integration.json": json.dumps(
                            {
                                "schemaVersion": 1,
                                "type": "iframe",
                                "entries": ["index.html", "runtime.js"],
                            }
                        ),
                        "index.html": "<html></html>",
                        "runtime.js": "window.runtime = true;",
                    }
                ),
                "application/zip",
            )
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "iframe 集成入口不能混合 HTML 与 JavaScript"


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
