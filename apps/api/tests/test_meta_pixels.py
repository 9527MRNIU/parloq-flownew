from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.services.meta_conversions import process_due_meta_conversions


def _template_zip() -> bytes:
    manifest = {
        "schema": "promotion-template/v2",
        "version": "2.0.0",
        "entry": "index.html",
        "format": "static-bundle",
        "capabilities": ["phone-pairing"],
        "runtime": "promotion-browser-bridge/v2",
        "requirements": {"pairingContract": "promotion-public-pairing/v1"},
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
        archive.writestr("index.html", '<form data-promotion-manual><input type="tel"></form>')
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("locales/en.json", '{"title":"Connect"}')
    return output.getvalue()


def test_meta_pixel_placeholder_crud_masks_capi_token(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/meta-pixels",
        json={
            "name": "Promotion Pixel",
            "datasetId": "1234567890",
            "capiToken": "meta-capi-secret",
        },
    )
    assert created.status_code == 201
    pixel = created.json()["data"]["pixel"]
    assert pixel["id"].isdecimal()
    assert "publicId" not in pixel
    assert pixel["capiTokenMasked"] == "••••cret"
    assert "meta-capi-secret" not in created.text

    updated = admin_client.patch(
        f"/api/meta-pixels/{pixel['id']}", json={"enabled": False}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["pixel"]["enabled"] is False


def test_channel_meta_config_enqueues_deduplicates_and_delivers_capi(
    admin_client: TestClient,
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
        },
    )
    assert pixel_response.status_code == 201, pixel_response.text
    pixel = pixel_response.json()["data"]["pixel"]
    assert pixel["capiTokenConfigured"] is True
    template_response = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Standard v2 test"},
        files={"file": ("standard-v2.zip", _template_zip(), "application/zip")},
    )
    assert template_response.status_code == 201, template_response.text
    template = template_response.json()["data"]["template"]
    assert template["manifest"]["schema"] == "promotion-template/v2"
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
            "metaBrowserPixelEnabled": True,
            "metaCapiEnabled": True,
            "metaEventMapping": {
                "page_view": "PageView",
                "phone_submit": "Lead",
                "pairing_started": "InitiateCheckout",
                "pairing_verified": "CompleteRegistration",
            },
            "inAppBrowserMode": "guide_external",
            "newAccountMarketingEnabled": False,
        },
    )
    assert channel_response.status_code == 201, channel_response.text
    channel = channel_response.json()["data"]["channel"]
    assert channel["effectiveConfig"]["template"]["runtime"] == (
        "promotion-browser-bridge/v2"
    )
    assert channel["effectiveConfig"]["route"]["mode"] == "node"
    assert channel["metaCapiEnabled"] is True

    public = admin_client.get(
        "/api/public/promotion/channels/meta-delivery-test"
    ).json()["data"]
    assert public["meta"]["browserEnabled"] is True
    event = {
        "eventType": "phone_submit",
        "idempotencyKey": "meta-lead-event-0001",
        "visitorId": "visitor-meta-ledger-0001",
        "sessionToken": public["sessionToken"],
        "phone": "12025550129",
    }
    first = admin_client.post(
        "/api/public/promotion/channels/meta-delivery-test/events", json=event
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["metaEvent"] == {
        "name": "Lead",
        "eventId": "meta-lead-event-0001",
    }
    duplicate = admin_client.post(
        "/api/public/promotion/channels/meta-delivery-test/events", json=event
    )
    assert duplicate.json()["data"]["duplicate"] is True

    ledger_url = f"/api/promotion/channels/{channel['id']}/meta-deliveries"
    pending = admin_client.get(ledger_url).json()["data"]
    assert pending["total"] == 1
    assert pending["rows"][0]["eventName"] == "Lead"
    assert pending["rows"][0]["status"] == "pending"
    result = process_due_meta_conversions()
    assert result == {"claimed": 1, "delivered": 1, "retry": 0, "failed": 0}
    delivered = admin_client.get(ledger_url).json()["data"]
    assert delivered["rows"][0]["status"] == "delivered"
    assert delivered["rows"][0]["providerTraceId"] == "mock"
