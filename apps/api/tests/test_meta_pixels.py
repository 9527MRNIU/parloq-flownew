from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.services.meta_conversions import process_due_meta_conversions


def _template_zip() -> bytes:
    manifest = {
        "schema": "promotion-template/v3",
        "version": "3.0.0",
        "entry": "index.html",
        "format": "static-bundle",
        "capabilities": ["phone-pairing"],
        "runtime": "promotion-browser-bridge/v2",
        "requirements": {
            "pairingContract": "promotion-public-pairing/v1",
        },
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
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "index.html",
            """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>
            <account-link-flow>
              <account-link-locale-switcher></account-link-locale-switcher>
              <phone-number-field></phone-number-field>
              <account-link-submit></account-link-submit>
              <pairing-code-panel></pairing-code-panel>
              <app-launch-actions></app-launch-actions>
              <account-link-status></account-link-status>
              <account-initialization-status></account-initialization-status>
            </account-link-flow>
            <script src="assets/account-link-elements.js"></script>
            </body></html>""",
        )
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("assets/account-link-elements.js", "window.testComponents = true;")
        archive.writestr("locales/en.json", '{"title":"Connect"}')
    return output.getvalue()


def test_meta_pixel_placeholder_crud_masks_capi_token(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/meta-pixels",
        json={
            "name": "Promotion Pixel",
            "datasetId": "1234567890",
            "capiToken": "meta-capi-secret",
            "browserPixelEnabled": True,
            "capiEnabled": True,
        },
    )
    assert created.status_code == 201
    pixel = created.json()["data"]["pixel"]
    assert pixel["id"].isdecimal()
    assert "publicId" not in pixel
    assert pixel["capiTokenMasked"] == "••••cret"
    assert pixel["browserPixelEnabled"] is True
    assert pixel["capiEnabled"] is True
    assert pixel["eventMapping"]["phone_submit"] == "Lead"
    assert "meta-capi-secret" not in created.text

    updated = admin_client.patch(
        f"/api/meta-pixels/{pixel['id']}", json={"enabled": False}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["pixel"]["enabled"] is False


def test_channel_meta_config_enqueues_deduplicates_and_delivers_capi(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    domain = admin_client.post(
        "/api/domains", json={"hostname": "meta-ledger.test"}
    ).json()["data"]["domain"]
    assert admin_client.post(f"/api/domains/{domain['id']}/verify").status_code == 200
    pixel_response = admin_client.post(
        "/api/meta-pixels",
        json={
            "name": "Meta delivery test",
            "datasetId": "meta-delivery-test-001",
            "capiToken": "meta-delivery-secret",
            "browserPixelEnabled": True,
            "capiEnabled": True,
            "eventMapping": {
                "page_view": "PageView",
                "phone_submit": "Lead",
                "pairing_started": "InitiateCheckout",
                "pairing_verified": "CompleteRegistration",
            },
        },
    )
    assert pixel_response.status_code == 201, pixel_response.text
    pixel = pixel_response.json()["data"]["pixel"]
    assert pixel["capiTokenConfigured"] is True
    template_response = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Standard v3 test"},
        files={"file": ("standard-v3.zip", _template_zip(), "application/zip")},
    )
    assert template_response.status_code == 201, template_response.text
    template = template_response.json()["data"]["template"]
    assert template["manifest"]["schema"] == "promotion-template/v3"
    assert template["manifest"]["runtime"] == "promotion-browser-bridge/v2"
    group = admin_client.post(
        "/api/account-groups", json={"name": "Meta delivery accounts"}
    ).json()["data"]["group"]
    channel_response = admin_client.post(
        "/api/promotion/channels",
        json={
            "type": "facebook",
            "name": "Meta delivery channel",
            "countryCode": "US",
            "templateId": template["id"],
            "domainId": domain["id"],
            "pixelId": pixel["id"],
            "accountGroupId": group["id"],
            "slug": "meta-delivery-test",
            "status": "active",
            "inAppBrowserMode": "guide_external",
            "newAccountMarketingEnabled": False,
        },
    )
    assert channel_response.status_code == 201, channel_response.text
    channel = channel_response.json()["data"]["channel"]
    assert channel["effectiveConfig"]["template"]["runtime"] == (
        "promotion-browser-bridge/v2"
    )
    assert channel["effectiveConfig"]["template"]["componentContract"] == (
        "account-link-elements/v1"
    )
    assert channel["effectiveConfig"]["route"]["mode"] == "node"
    assert channel["metaCapiEnabled"] is True
    assert channel["metaCapiProbeReady"] is True
    assert channel["metaDomainMonitored"] is True
    assert channel["metaDomainBlocked"] is False

    ledger_url = f"/api/promotion/channels/{channel['id']}/meta-deliveries"
    probe = admin_client.post(
        f"/api/promotion/channels/{channel['id']}/meta-capi-probe"
    )
    assert probe.status_code == 200, probe.text
    probe_result = probe.json()["data"]
    assert probe_result["ok"] is True
    assert probe_result["eventName"] == "ParloqCapiProbe"
    assert probe_result["eventId"].startswith("parloq-probe-")
    assert probe_result["providerTraceId"] == "mock-probe"
    assert admin_client.get(ledger_url).json()["data"]["total"] == 0

    public = admin_client.get(
        "/api/public/promotion/channels/meta-delivery-test"
    ).json()["data"]
    assert public["meta"]["browserEnabled"] is True
    assert public["metaDomainReportUrl"].endswith(
        "/meta-domain-unavailable"
    )
    unavailable = admin_client.post(
        public["metaDomainReportUrl"],
        content=json.dumps(
            {
                "datasetId": public["meta"]["datasetId"],
            }
        ),
        headers={"content-type": "text/plain;charset=UTF-8"},
    )
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json()["data"]["affectedChannels"] == 1
    duplicate_unavailable = admin_client.post(
        public["metaDomainReportUrl"],
        content=json.dumps(
            {
                "datasetId": public["meta"]["datasetId"],
            }
        ),
        headers={"content-type": "text/plain;charset=UTF-8"},
    )
    assert duplicate_unavailable.json()["data"]["duplicate"] is True
    from app.services.promotion_event_rate_limits import (
        PromotionEventRateLimitDecision,
    )

    with monkeypatch.context() as context:
        context.setattr(
            "app.routers.promotion.consume_promotion_event_rate_limits",
            lambda *_args, **_kwargs: PromotionEventRateLimitDecision(
                allowed=False,
                retry_after_seconds=29,
                policy_key="metaDomainReports",
                limit=1,
            ),
        )
        limited_domain_report = admin_client.post(
            public["metaDomainReportUrl"],
            content=json.dumps(
                {
                    "datasetId": public["meta"]["datasetId"],
                }
            ),
            headers={"content-type": "text/plain;charset=UTF-8"},
        )
    assert limited_domain_report.status_code == 429
    assert limited_domain_report.headers["retry-after"] == "29"
    assert limited_domain_report.json()["error"]["code"] == (
        "report_rate_limited"
    )
    monitored = admin_client.get(
        f"/api/promotion/channels/{channel['id']}"
    ).json()["data"]["channel"]
    assert monitored["metaDomainBlocked"] is True
    assert monitored["metaDomainBlockedAt"]

    reset = admin_client.patch(
        f"/api/meta-pixels/{pixel['id']}",
        json={"browserPixelEnabled": False},
    )
    assert reset.status_code == 200, reset.text
    reset_channel = admin_client.get(
        f"/api/promotion/channels/{channel['id']}"
    ).json()["data"]["channel"]
    assert reset_channel["metaDomainBlocked"] is False
    assert reset_channel["metaDomainMonitored"] is False
    reenabled = admin_client.patch(
        f"/api/meta-pixels/{pixel['id']}",
        json={"browserPixelEnabled": True},
    )
    assert reenabled.status_code == 200, reenabled.text
    reenabled_channel = admin_client.get(
        f"/api/promotion/channels/{channel['id']}"
    ).json()["data"]["channel"]
    assert reenabled_channel["metaDomainMonitored"] is True
    stale_report = admin_client.post(
        public["metaDomainReportUrl"],
        content=json.dumps(
            {
                "datasetId": "stale-dataset-id",
            }
        ),
        headers={"content-type": "text/plain;charset=UTF-8"},
    )
    assert stale_report.status_code == 409

    pairing_payload = {
        "phone": "12025550129",
        "deviceFingerprint": "7ef8bdbc97de077c45a46358ecc4ba42",
    }
    first = admin_client.post(
        "/api/public/promotion/channels/meta-delivery-test/pairing/start",
        json=pairing_payload,
    )
    assert first.status_code in {200, 409}, first.text
    if first.status_code == 409:
        assert first.json()["error"]["code"] == "connection_route_unavailable"
    duplicate = admin_client.post(
        "/api/public/promotion/channels/meta-delivery-test/pairing/start",
        json=pairing_payload,
    )
    assert duplicate.status_code == first.status_code, duplicate.text

    pending = admin_client.get(ledger_url).json()["data"]
    assert pending["total"] in {1, 2, 3}
    lead_delivery = next(row for row in pending["rows"] if row["eventName"] == "Lead")
    assert lead_delivery["eventName"] == "Lead"
    assert lead_delivery["status"] == "pending"
    result = process_due_meta_conversions()
    assert result == {
        "claimed": pending["total"],
        "delivered": pending["total"],
        "retry": 0,
        "failed": 0,
    }
    delivered = admin_client.get(ledger_url).json()["data"]
    delivered_lead = next(row for row in delivered["rows"] if row["eventName"] == "Lead")
    assert delivered_lead["status"] == "delivered"
    assert delivered_lead["providerTraceId"] == "mock"
