from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.business_schemas import PublicEvent
from app.database import SessionLocal
from app.models import PromotionIntegration
from app.validation import PROMOTION_INTEGRATION_EVENT_MAX_BYTES


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _template_zip(body: str) -> bytes:
    components = """<account-link-flow>
    <account-link-locale-switcher></account-link-locale-switcher>
    <phone-number-field></phone-number-field>
    <account-link-submit></account-link-submit>
    <pairing-code-panel></pairing-code-panel>
    <app-launch-actions></app-launch-actions>
    <account-link-status></account-link-status>
    <account-initialization-status></account-initialization-status>
    </account-link-flow>"""
    manifest = {
        "schema": "promotion-template/v3",
        "version": "3.0.0",
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
    html = body.replace(
        "</body>",
        f'{components}<script src="assets/account-link-elements.js"></script></body>',
    )
    return _zip(
        {
            "index.html": html,
            "manifest.json": json.dumps(manifest),
            "assets/account-link-elements.js": "window.testComponents = true;",
            "locales/en.json": "{}",
        }
    )


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
                "frame/extract.js.enc": "opaque-ciphertext-fixture",
            }
        ),
    )
    assert iframe["id"].isdecimal()
    assert iframe["type"] == "iframe"
    assert iframe["entryPaths"] == ["index.html"]
    assert iframe["assetCount"] == 5
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

    opaque_url = iframe["sourceUrls"][0].rsplit("/", 1)[0] + "/extract.js.enc"
    opaque_asset = admin_client.get(
        opaque_url.removeprefix("https://integration-source.test"),
        headers={"host": "integration-source.test"},
    )
    assert opaque_asset.status_code == 200, opaque_asset.text
    assert opaque_asset.content == b"opaque-ciphertext-fixture"
    assert opaque_asset.headers["content-type"] == "application/octet-stream"
    assert opaque_asset.headers["x-content-type-options"] == "nosniff"

    wrong_host = admin_client.get(
        script["sourceUrls"][0].removeprefix("https://integration-source.test"),
        headers={"host": "other.test"},
    )
    assert wrong_host.status_code == 404

    template_bundle = _template_zip(
        "<html><head><title>Integration template</title></head>"
        "<body><main>Landing</main></body></html>"
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


def test_iframe_manifest_requires_an_html_entry(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "javascript-frame.test")
    response = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "javascript-frame-v1",
            "name": "全 JavaScript iframe",
            "domainId": domain["id"],
        },
        files={
            "file": (
                "javascript-frame-v1.zip",
                _zip(
                    {
                        "integration.json": json.dumps(
                            {
                                "schemaVersion": 1,
                                "type": "iframe",
                                "version": "3.1.0",
                                "entries": ["ds_net.js", "ds_net_native.mjs"],
                            }
                        ),
                        "ds_net.js": "window.loadOrder = ['web'];",
                        "ds_net_native.mjs": "window.loadOrder.push('native');",
                    }
                ),
                "application/zip",
            )
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "iframe 集成入口必须是 .html 或 .htm"

    missing_html = admin_client.post(
        "/api/promotion/integrations",
        data={
            "integrationKey": "javascript-frame-without-entry",
            "name": "缺少 HTML 的 iframe",
            "domainId": domain["id"],
        },
        files={
            "file": (
                "javascript-frame-without-entry.zip",
                _zip(
                    {
                        "integration.json": json.dumps(
                            {"schemaVersion": 1, "type": "iframe"}
                        ),
                        "main.js": "window.onlyJavaScript = true;",
                    }
                ),
                "application/zip",
            )
        },
    )
    assert missing_html.status_code == 422, missing_html.text
    assert (
        missing_html.json()["detail"]
        == "iframe 集成包必须包含 HTML 或 HTM 入口"
    )


def test_legacy_javascript_iframe_entries_are_not_injected(
    admin_client: TestClient,
) -> None:
    domain = _verified_domain(admin_client, "legacy-javascript-frame.test")
    integration = _create_integration(
        admin_client,
        domain_id=domain["id"],
        key="legacy-javascript-frame",
        name="旧版纯 JavaScript iframe",
        package=_zip(
            {
                "index.html": "<html><body></body></html>",
                "legacy.js": "window.legacyIframe = true;",
            }
        ),
    )
    imported = admin_client.post(
        "/api/promotion/templates",
        data={
            "name": "Legacy iframe template",
            "integrationIds": json.dumps([integration["id"]]),
        },
        files={
            "file": (
                "legacy-iframe-template.zip",
                _template_zip("<html><body>Landing</body></html>"),
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]

    with SessionLocal.begin() as db:
        stored = db.get(PromotionIntegration, int(integration["id"]))
        assert stored is not None
        stored.entrypoints_json = [{"path": "legacy.js", "scriptType": "classic"}]

    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert "legacy.js" not in preview.text
    assert "frame-src 'none'" in preview.headers["content-security-policy"]


def test_iframe_feedback_uses_an_independent_runtime_and_persists_events(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    from app.services.request_network import RequestNetwork

    monkeypatch.setattr(
        "app.routers.promotion_integrations.resolve_request_network",
        lambda _request: RequestNetwork("198.51.100.42", "JP", "cloudflare"),
    )
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
                _template_zip("<html><head></head><body>Landing</body></html>"),
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
    assert "#parloqChannel=feedback-channel-v1" in rendered.text
    assert "parloqTrafficSource=direct" in rendered.text
    assert "parloqEmbedToken" not in rendered.text
    event_url = (
        f"/api/public/promotion/integrations/{integration['id']}"
        "/channels/feedback-channel-v1/events"
    )

    event_payload = {
        "eventType": "completed",
        "deviceFingerprint": "0ef8bdbc97de077c45a46358ecc4ba42",
        "metadata": {"result": "ok", "count": 2},
    }
    event = admin_client.post(
        event_url,
        headers={
            "host": "integration-feedback.test",
            "user-agent": "Mozilla/5.0 Chrome/151.0.0.0 Safari/537.36",
            "accept-language": "ja-JP,ja;q=0.9",
        },
        json=event_payload,
    )
    assert event.status_code == 201, event.text
    assert event.json()["data"]["duplicate"] is False
    event_id = event.json()["data"]["eventId"]
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
            event_url,
            headers={"host": "integration-feedback.test"},
            json={
                **event_payload,
            },
        )
    assert limited.status_code == 429, limited.text
    assert limited.headers["retry-after"] == "23"
    assert limited.json()["error"]["code"] == "report_rate_limited"

    undeclared = admin_client.post(
        event_url,
        headers={"host": "integration-feedback.test"},
        json={**event_payload, "eventType": "not_declared"},
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
        event_url,
        headers={"host": "integration-feedback.test"},
        json={
            **event_payload,
            "metadata": boundary_metadata,
        },
    )
    assert boundary.status_code == 201, boundary.text

    metadata_too_large = admin_client.post(
        event_url,
        headers={"host": "integration-feedback.test"},
        json={
            **event_payload,
            "metadata": {"blob": boundary_metadata["blob"] + "x"},
        },
    )
    assert metadata_too_large.status_code == 422, metadata_too_large.text

    envelope_too_large = admin_client.post(
        event_url,
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
    stored_metadata = {
        "result": "ok",
        "count": 2,
        "deviceFingerprint": {
            "version": "thumbmarkjs/1.10.1",
            "profile": "thumbmarkjs",
            "quality": "high",
        },
    }
    encoded_metadata = json.dumps(
        stored_metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert event_row["metadataBytes"] == len(encoded_metadata)
    assert event_row["metadataSha256"] == hashlib.sha256(encoded_metadata).hexdigest()

    event_detail = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}/events/{event_id}"
    )
    assert event_detail.status_code == 200, event_detail.text
    detail_data = event_detail.json()["data"]["event"]
    assert detail_data["metadata"] == stored_metadata
    assert detail_data["metadataBytes"] == len(encoded_metadata)
    assert detail_data["metadataSha256"] == hashlib.sha256(encoded_metadata).hexdigest()

    boundary_event_id = boundary.json()["data"]["eventId"]
    boundary_detail = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}/events/{boundary_event_id}"
    )
    assert boundary_detail.status_code == 200, boundary_detail.text
    assert boundary_detail.json()["data"]["event"]["metadata"]["blob"] == boundary_metadata["blob"]

    monitoring = admin_client.get(
        f"/api/promotion/monitoring/records?integrationId={integration['id']}"
    )
    assert monitoring.status_code == 200, monitoring.text
    monitoring_data = monitoring.json()["data"]
    assert monitoring_data["total"] == 2
    monitored_record = next(
        row for row in monitoring_data["rows"] if row["id"] == event_id
    )
    assert monitored_record["source"] == "integration"
    assert monitored_record["eventType"] == "completed"
    assert monitored_record["integration"]["version"] == integration["version"]
    assert monitored_record["sourceIp"] == "198.51.100.42"
    assert monitored_record["visitorCountryCode"] == "JP"
    assert monitored_record["networkSource"] == "cloudflare"
    assert monitored_record["device"]["browser"] == "Chrome"
    assert monitored_record["device"]["browserVersion"] == "151.0.0.0"
    monitored_detail = admin_client.get(
        f"/api/promotion/monitoring/records/integration/{event_id}"
    )
    assert monitored_detail.status_code == 200, monitored_detail.text
    monitoring_detail = monitored_detail.json()["data"]["record"]
    assert monitoring_detail["metadata"] == stored_metadata
    assert monitoring_detail["sourceIp"] == "198.51.100.42"
    assert monitoring_detail["visitorCountryCode"] == "JP"
    assert monitoring_detail["requestContext"]["language"] == "ja-JP"
    assert monitoring_detail["requestContext"]["userAgent"].endswith(
        "Chrome/151.0.0.0 Safari/537.36"
    )

    refreshed = admin_client.get(
        f"/api/promotion/integrations/{integration['id']}"
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["data"]["integration"]["eventCount"] == 2


def test_public_event_metadata_limit_remains_4_kib() -> None:
    with pytest.raises(ValidationError, match="JSON 内容过大"):
        PublicEvent(
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


def test_iframe_manifest_rejects_non_html_entries(
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
    assert response.json()["detail"] == "iframe 集成入口必须是 .html 或 .htm"


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
