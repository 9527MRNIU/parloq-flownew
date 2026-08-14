from __future__ import annotations

import io
import hashlib
import hmac
import json
import re
import zipfile
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AccountLifecycleEvent, PersonalAccount
from app.routers.promotion import _localize_template_html
from app.security import utcnow
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.task_worker import process_task


def _zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_server_side_template_localization_escapes_copy_and_attributes() -> None:
    source = (
        '<html lang="en"><head><title>Default</title></head><body>'
        '<h1 data-copy="title">Default</h1>'
        '<input data-copy-placeholder="phonePlaceholder" placeholder="default">'
        "</body></html>"
    )
    rendered = _localize_template_html(
        source,
        "ar-SA",
        {
            "title": "تابع <بأمان> & الآن",
            "phonePlaceholder": '\\1" <unsafe>',
        },
    )
    assert '<html lang="ar-SA" dir="rtl">' in rendered
    assert "<title>تابع &lt;بأمان&gt; &amp; الآن</title>" in rendered
    assert '<h1 data-copy="title">تابع &lt;بأمان&gt; &amp; الآن</h1>' in rendered
    assert 'placeholder="\\1&amp;quot; &amp;lt;unsafe&amp;gt;"' not in rendered
    assert 'placeholder="\\1&quot; &lt;unsafe&gt;"' in rendered


def _gateway_event(client: TestClient, message_id: str, account_id: str, event_status: str):
    body = json.dumps(
        {
            "event": "message.status",
            "messageId": message_id,
            "accountId": account_id,
            "status": event_status,
            "timestamp": "2026-08-12T10:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"pytest-wa-webhook-secret", body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/internal/wa-gateway/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Parloq-Signature": f"sha256={signature}",
        },
    )


def _gateway_account_event(
    client: TestClient,
    *,
    event_id: str,
    account_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    occurred_at,
):
    body = json.dumps(
        {
            "event": "account.state",
            "eventId": event_id,
            "accountId": account_id,
            "fromState": from_state,
            "toState": to_state,
            "reasonCategory": reason,
            "providerCode": "403" if to_state == "restricted" else None,
            "occurredAt": occurred_at.isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"pytest-wa-webhook-secret", body, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/api/internal/wa-gateway/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Parloq-Signature": f"sha256={signature}",
        },
    )


def test_account_state_webhook_is_durable_idempotent_and_ordered(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/personal-accounts",
        json={"name": "State webhook", "phone": "+12025550771"},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["data"]["account"]["id"]
    restricted_at = utcnow()
    restricted = _gateway_account_event(
        admin_client,
        event_id="ast_restricted_test",
        account_id=account_id,
        from_state="online_idle",
        to_state="restricted",
        reason="restricted",
        occurred_at=restricted_at,
    )
    assert restricted.status_code == 200, restricted.text
    assert restricted.json()["data"] == {
        "ok": True,
        "duplicate": False,
        "applied": True,
        "eventId": "ast_restricted_test",
    }
    duplicate = _gateway_account_event(
        admin_client,
        event_id="ast_restricted_test",
        account_id=account_id,
        from_state="online_idle",
        to_state="restricted",
        reason="restricted",
        occurred_at=restricted_at,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["duplicate"] is True

    stale = _gateway_account_event(
        admin_client,
        event_id="ast_stale_connected_test",
        account_id=account_id,
        from_state="warming",
        to_state="online_idle",
        reason="connected",
        occurred_at=restricted_at - timedelta(days=1),
    )
    assert stale.status_code == 200
    assert stale.json()["data"]["applied"] is False

    detail = admin_client.get(f"/api/personal-accounts/{account_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["account"]["status"] == "restricted"
    with SessionLocal() as db:
        account = db.scalar(
            select(PersonalAccount).where(PersonalAccount.public_id == account_id)
        )
        assert account is not None
        events = db.scalars(
            select(AccountLifecycleEvent).where(
                AccountLifecycleEvent.account_id == account.id
            )
        ).all()
        assert {event.public_id for event in events} >= {
            f"initial_{account_id}",
            "ast_restricted_test",
            "ast_stale_connected_test",
        }


def test_interrupted_pairing_webhook_marks_account_retryable(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Interrupted pairing", "phone": "+12025550772"},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["data"]["account"]["id"]

    interrupted = _gateway_account_event(
        admin_client,
        event_id="ast_pairing_interrupted_test",
        account_id=account_id,
        from_state="pairing",
        to_state="unpaired",
        reason="pairing_connection_lost",
        occurred_at=utcnow(),
    )
    assert interrupted.status_code == 200, interrupted.text

    account = admin_client.get(
        "/api/personal-accounts?keyword=12025550772"
    ).json()["data"]["rows"][0]
    assert account["status"] == "unpaired"
    assert account["validationStatus"] == "failed"
    assert account["lastError"] == "配对连接已中断，请重新获取配对码"


def test_promotion_zip_channel_tracking_leads_and_insights(admin_client: TestClient) -> None:
    domain = admin_client.post("/api/domains", json={"hostname": "promo-example.test"})
    assert domain.status_code == 201
    domain_id = domain.json()["data"]["domain"]["id"]
    verified = admin_client.post(f"/api/domains/{domain_id}/verify")
    assert verified.status_code == 200
    assert verified.json()["data"]["domain"]["sslStatus"] == "verified"

    pixel = admin_client.post(
        "/api/meta-pixels", json={"name": "Promotion Pixel", "datasetId": "promo-dataset-001"}
    )
    assert pixel.status_code == 201
    pixel_id = pixel.json()["data"]["pixel"]["id"]

    # A pure single-page ZIP is valid; manifest and assets are optional.
    initial = _zip({"index.html": "<HTML><HEAD></HEAD><body><form><input type='tel'></form></body></HTML>"})
    imported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Vite Promotion Template"},
        files={"file": ("promotion.zip", initial, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    assert template["manifest"]["schema"] == "parloq-promotion-template/v1"
    assert template["manifest"]["runtime"] == "parloq-browser-bridge/v1"
    assert template["manifest"]["capabilities"] == ["phone-pairing"]
    assert template["defaultLocale"] == "en"
    assert template["supportedLocales"] == ["en"]

    manifest = {
        "version": "2",
        "defaultLocale": "en",
        "supportedLocales": ["en", "de", "ar", "fr"],
        "i18n": {
            "mode": "bundled",
            "path": "locales/{locale}.json",
            "fallbackLocale": "en",
        },
    }
    replacement = _zip(
        {
            "dist/index.html": '<html lang="en"><head><title>Hello</title><link rel="stylesheet" href="assets/app.css"><script type="module" src="assets/app.js"></script></head><body><h1 data-copy="title">Hello</h1><input data-copy-placeholder="phonePlaceholder" placeholder="12025550123"><img src="/assets/logo.png"></body></html>',
            "dist/manifest.json": json.dumps(manifest),
            "dist/assets/app.js": "window.templateLoaded=true",
            "dist/assets/app.css": "body{color:#123456}",
            "dist/assets/logo.png": "demo",
            "dist/locales/en.json": '{"title":"Hello","phonePlaceholder":"12025550123"}',
            "dist/locales/de.json": '{"title":"Hallo","phonePlaceholder":"4915123456789"}',
            "dist/locales/ar.json": '{"title":"تابع برقم هاتفك","phonePlaceholder":"966501234567"}',
        }
    )
    replaced = admin_client.post(
        f"/api/promotion/templates/{template['id']}/versions",
        files={"file": ("dist.zip", replacement, "application/zip")},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["data"]["template"]["version"] == "2"
    replaced_again = admin_client.post(
        f"/api/promotion/templates/{template['id']}/versions",
        files={"file": ("dist.zip", replacement, "application/zip")},
    )
    assert replaced_again.status_code == 200, replaced_again.text
    preview = admin_client.get(f"/api/promotion/templates/{template['id']}/preview")
    assert preview.status_code == 200
    signed_base_match = re.search(
        rf'<base href="(/api/promotion/templates/{template["id"]}/preview/assets/_signed/[^/]+/)">',
        preview.text,
    )
    assert signed_base_match is not None
    signed_asset_root = signed_base_match.group(1)
    assert 'src="assets/app.js"' in preview.text
    assert 'type="module"' in preview.text
    assert preview.text.index("<base ") < preview.text.index("<link ")
    assert preview.text.index("<base ") < preview.text.index('src="assets/app.js"')
    assert f"{signed_asset_root}assets/logo.png" in preview.text
    assert "/assets/assets/assets/" not in preview.text
    assert "sandbox allow-scripts allow-forms" in preview.headers[
        "content-security-policy"
    ]
    assert "form-action 'none'" in preview.headers["content-security-policy"]
    assert "allow-same-origin" not in preview.headers["content-security-policy"]
    assert "connect-src http://testserver" in preview.headers["content-security-policy"]
    assert '"previewMode": true' in preview.text
    assert '"templatePolicy": {' in preview.text
    assert '"deviceSignals": "enhanced"' in preview.text
    assert "window.parloqSubmitPhone" in preview.text
    assert 'addEventListener("contextmenu"' in preview.text
    assert 'e.key==="F12"' in preview.text
    assert admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview/assets/assets/app.js"
    ).status_code == 200
    assert admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview/assets/assets/app.css"
    ).status_code == 200
    assert admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview/assets/locales/de.json"
    ).status_code == 200
    signed_css = admin_client.get(f"{signed_asset_root}assets/app.css")
    assert signed_css.status_code == 200
    assert signed_css.headers["access-control-allow-origin"] == "*"
    tampered_root = signed_asset_root.replace("_signed/", "_signed/x", 1)
    assert admin_client.get(f"{tampered_root}assets/app.css").status_code == 404
    preview_token = signed_asset_root.rstrip("/").rsplit("/", 1)[-1]
    preview_status = admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview/pairing-status",
        params={"token": preview_token},
    )
    assert preview_status.status_code == 200
    assert preview_status.json()["data"] == {
        "state": "ready",
        "accountState": "linked_offline",
        "pairingStatus": "verified",
        "verified": True,
        "preview": True,
    }

    channel = admin_client.post(
        "/api/promotion/channels",
        json={
            "type": "facebook",
            "name": "Germany Facebook",
            "countryCode": "DE",
            "templatePublicId": template["id"],
            "domainPublicId": domain_id,
            "pixelPublicId": pixel_id,
            "slug": "de-facebook-demo",
            "status": "active",
            "localeMode": "auto",
        },
    )
    assert channel.status_code == 201, channel.text
    channel_id = channel.json()["data"]["channel"]["id"]

    public_config = admin_client.get("/api/public/promotion/channels/de-facebook-demo?lang=de")
    assert public_config.status_code == 200
    config = public_config.json()["data"]
    assert config["resolvedLocale"] == "de"
    assert config["countryCode"] == "DE"
    session_token = config["sessionToken"]
    invalid = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json={
            "eventType": "page_view",
            "idempotencyKey": "invalid-token-event",
            "sessionToken": "invalid-token-payload.invalid-signature",
        },
    )
    assert invalid.status_code == 403

    page_view = {
        "eventType": "page_view",
        "idempotencyKey": "page-view-event-0001",
        "sessionToken": session_token,
    }
    assert admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events", json=page_view
    ).status_code == 200
    lead = {
        "eventType": "phone_submit",
        "idempotencyKey": "phone-lead-event-0001",
        "sessionToken": session_token,
        "phone": "+49 151 23456789",
    }
    first = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events", json=lead
    )
    assert first.status_code == 200
    duplicate = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events", json=lead
    )
    assert duplicate.json()["data"]["duplicate"] is True
    leads = admin_client.get(f"/api/promotion/channels/{channel_id}/leads").json()["data"]
    assert leads["total"] == 1
    assert leads["rows"][0]["phone"] == "+4915123456789"
    stats = admin_client.get(f"/api/promotion/channels/{channel_id}/stats").json()["data"]
    assert stats["totals"]["pageView"] == 1
    assert stats["totals"]["phoneSubmit"] == 1
    policy = admin_client.patch(
        "/api/promotion/template-policy",
        json={
            "protectionMode": "strict",
            "devtoolsAction": "blank",
            "lockViewportZoom": True,
            "deviceSignals": "enhanced",
        },
    )
    assert policy.status_code == 200, policy.text
    render = admin_client.get("/api/public/promotion/channels/de-facebook-demo/render?lang=de")
    assert "parloq-promotion-config" in render.text
    assert 'src="/api/public/promotion/guard.js"' in render.text
    assert '<base href="/api/public/promotion/channels/de-facebook-demo/assets/">' in render.text
    assert render.text.index("<base ") < render.text.index("<link ")
    assert render.text.index("<base ") < render.text.index('src="assets/app.js"')
    assert '"pixelDatasetId": "promo-dataset-001"' in render.text
    assert '"templatePolicy": {' in render.text
    assert '"protectionMode": "strict"' in render.text
    assert '"devtoolsAction": "blank"' in render.text
    assert '"deviceSignals": "enhanced"' in render.text
    assert render.headers["content-language"] == "de"
    assert '<html lang="de" dir="ltr">' in render.text
    assert "<title>Hallo</title>" in render.text
    assert '<h1 data-copy="title">Hallo</h1>' in render.text
    assert 'placeholder="4915123456789"' in render.text
    assert '"localizedCopy": {"title": "Hallo"' in render.text
    assert "maximum-scale=1,user-scalable=no" in render.text
    assert 'src="assets/app.js"' in render.text
    assert "/api/public/promotion/channels/de-facebook-demo/assets/assets/logo.png" in render.text
    assert "/assets/assets/assets/" not in render.text
    rtl_render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render?lang=ar"
    )
    assert rtl_render.headers["content-language"] == "ar"
    assert '<html lang="ar" dir="rtl">' in rtl_render.text
    assert "<title>تابع برقم هاتفك</title>" in rtl_render.text
    fallback_render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render?lang=fr"
    )
    assert fallback_render.headers["content-language"] == "en"
    assert '<html lang="en" dir="ltr">' in fallback_render.text
    assert "<title>Hello</title>" in fallback_render.text
    assert '"resolvedLocale": "en"' in fallback_render.text
    assert admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/assets/assets/app.js"
    ).status_code == 200
    assert admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/assets/assets/app.css"
    ).status_code == 200
    locale_asset = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/assets/locales/de.json"
    )
    assert locale_asset.status_code == 200
    assert locale_asset.json()["title"] == "Hallo"
    tracker = admin_client.get("/api/public/promotion/tracker.js")
    assert "connect.facebook.net/en_US/fbevents.js" in tracker.text
    assert '"track","Lead"' in tracker.text
    assert "pairingStartUrl" in tracker.text
    assert "pairing_start_failed" in tracker.text
    assert "form[data-parloq-manual]" in tracker.text
    assert 'send("page_view",{metadata:{deviceSignals:signals()}})' in tracker.text
    assert '"inspection_detected"' in tracker.text
    guard = admin_client.get("/api/public/promotion/guard.js")
    assert guard.status_code == 200
    assert 'addEventListener("contextmenu"' in guard.text
    assert 'e.key==="F12"' in guard.text
    assert 'window-gap' in guard.text
    assert 'debugger-delay' in guard.text

    inspection = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        content=json.dumps(
            {
                "eventType": "inspection_detected",
                "idempotencyKey": "inspection-event-0001",
                "visitorId": "visitor-inspection-0001",
                "sessionToken": config["sessionToken"],
                "metadata": {"reason": "window-gap", "mode": "enhanced"},
            }
        ),
    )
    assert inspection.status_code == 200, inspection.text
    reset_policy = admin_client.patch(
        "/api/promotion/template-policy",
        json={
            "protectionMode": "basic",
            "devtoolsAction": "log",
            "lockViewportZoom": False,
            "deviceSignals": "standard",
        },
    )
    assert reset_policy.status_code == 200, reset_policy.text

    metric = admin_client.post(
        "/api/promotion/ad-metrics",
        json={
            "date": "2026-08-12",
            "promotionChannelId": channel_id,
            "spend": 120.5,
            "impressions": 10000,
            "clicks": 500,
        },
    )
    assert metric.status_code == 201, metric.text
    summary = admin_client.get(
        f"/api/promotion/ad-metrics/summary?promotionChannelId={channel_id}"
    ).json()["data"]
    assert summary["leads"] == 1
    assert summary["costPerLead"] == 120.5

    # Sandboxed previews have an opaque origin, so their subresources cannot
    # rely on the control-plane login cookie. The signed capability works
    # anonymously, while the legacy asset route remains protected.
    admin_client.cookies.clear()
    assert admin_client.get(f"{signed_asset_root}assets/app.css").status_code == 200
    assert admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview/assets/assets/app.css"
    ).status_code == 401


def test_promotion_template_v1_rejects_unknown_schema_and_source_maps(
    admin_client: TestClient,
) -> None:
    unknown_schema = _zip(
        {
            "index.html": '<form><input type="tel"></form>',
            "manifest.json": json.dumps(
                {
                    "schema": "parloq-promotion-template/v2",
                    "capabilities": ["phone-pairing"],
                }
            ),
        }
    )
    unsupported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Unsupported schema"},
        files={"file": ("unknown.zip", unknown_schema, "application/zip")},
    )
    assert unsupported.status_code == 422
    assert "schema" in unsupported.json()["detail"]

    source_map = _zip(
        {
            "index.html": '<form><input type="tel"></form>',
            "assets/app.js.map": "{}",
        }
    )
    rejected_map = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Source map bundle"},
        files={"file": ("source-map.zip", source_map, "application/zip")},
    )
    assert rejected_map.status_code == 422
    assert "app.js.map" in rejected_map.json()["detail"]


def test_personal_account_gateway_and_hyperlink_delivery(
    admin_client: TestClient, monkeypatch
) -> None:
    proxy = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "WA Dedicated Proxy",
            "protocol": "socks5",
            "host": "proxy-wa.example.test",
            "port": 1080,
            "username": "secret-user",
            "password": "secret-pass",
            "countryCode": "US",
        },
    )
    assert proxy.status_code == 201
    proxy_id = proxy.json()["data"]["proxy"]["id"]
    original_create = WaGatewayClient.create
    observed_persisted_account: dict[str, bool] = {}

    def create_after_account_commit(self, account_id, phone, proxy_url):
        with SessionLocal() as independent_db:
            observed_persisted_account[account_id] = (
                independent_db.scalar(
                    select(PersonalAccount).where(
                        PersonalAccount.public_id == account_id
                    )
                )
                is not None
            )
        return original_create(self, account_id, phone, proxy_url)

    monkeypatch.setattr(WaGatewayClient, "create", create_after_account_commit)
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    landing_pair = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456790",
            "visitorId": "landing-visitor-0001",
            "sessionToken": public_config["sessionToken"],
        },
    )
    assert landing_pair.status_code == 200, landing_pair.text
    pairing = landing_pair.json()["data"]["pairing"]
    assert observed_persisted_account[pairing["statusUrl"].split("/")[-2]] is True
    assert pairing["pairingCode"] == "0000-0000"
    pairing_preflight = admin_client.options(
        pairing["statusUrl"],
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Parloq-Pairing-Token",
        },
    )
    assert pairing_preflight.status_code == 204
    assert pairing_preflight.headers["access-control-allow-origin"] == "null"
    assert (
        pairing_preflight.headers["access-control-allow-headers"]
        == "X-Parloq-Pairing-Token"
    )
    unrelated_preflight = admin_client.options(
        "/api/users",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Parloq-Pairing-Token",
        },
    )
    assert unrelated_preflight.status_code == 400
    landing_status = admin_client.get(
        pairing["statusUrl"],
        headers={
            "Origin": "null",
            "X-Parloq-Pairing-Token": pairing["statusToken"],
        },
    )
    assert landing_status.status_code == 200
    assert landing_status.headers["access-control-allow-origin"] == "null"
    status_data = landing_status.json()["data"]
    assert status_data["state"] == "ready"
    assert status_data["accountState"] == "linked_offline"
    assert status_data["pairingStatus"] == "verified"
    assert status_data["verified"] is True
    assert status_data["attemptId"] == pairing["attemptId"]
    landing_account = admin_client.get(
        "/api/personal-accounts?keyword=4915123456790"
    ).json()["data"]["rows"][0]
    assert landing_account["source"] == "landing_page"
    assert landing_account["sourceRefId"] == public_config["channel"]["id"]
    assert landing_account["validationStatus"] == "ready"
    account = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "US Sender",
            "phone": "+12025550111",
            "countryCode": "US",
            "proxyPublicId": proxy_id,
        },
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["data"]["account"]["id"]
    paired = admin_client.post(
        f"/api/personal-accounts/{account_id}/pairing-code",
        json={"method": "pairing_code"},
    )
    assert paired.status_code == 200
    assert paired.json()["data"]["pairingCode"] == "0000-0000"
    assert admin_client.post(f"/api/personal-accounts/{account_id}/connect").status_code == 200
    sent = admin_client.post(
        f"/api/personal-accounts/{account_id}/send",
        json={
            "to": "+12025550112",
            "message": "hello",
            "idempotencyKey": "manual-message-0001",
        },
    )
    assert sent.status_code == 200
    delivery = sent.json()["data"]["messageDelivery"]
    assert delivery["status"] == "queued"
    assert re.fullmatch(r"msg_\d+", delivery["messageId"])
    assert delivery["requestId"] == "manual-message-0001"
    assert "message" not in delivery
    assert admin_client.post(
        "/api/internal/wa-gateway/events",
        content=b"{}",
        headers={"X-Parloq-Signature": "sha256=invalid"},
    ).status_code == 401
    sent_event = _gateway_event(admin_client, delivery["messageId"], account_id, "sent")
    assert sent_event.status_code == 200
    delivered = _gateway_event(admin_client, delivery["messageId"], account_id, "read")
    assert delivered.status_code == 200
    duplicate = _gateway_event(admin_client, delivery["messageId"], account_id, "delivered")
    assert duplicate.json()["data"]["duplicate"] is True
    account_detail = admin_client.get(f"/api/personal-accounts/{account_id}").json()["data"]["account"]
    assert account_detail["sentCount"] == 1
    assert account_detail["deliveredCount"] == 1

    material = admin_client.post(
        "/api/hyperlink/materials",
        json={"name": "Text CTA", "type": "text", "contentJson": {"text": "offer"}},
    ).json()["data"]["material"]
    template = admin_client.post(
        "/api/hyperlink/templates",
        json={
            "name": "Offer Template",
            "contentJson": {"text": "Hello {{name}}"},
            "materialId": material["id"],
        },
    ).json()["data"]["template"]
    strategy = admin_client.post(
        "/api/hyperlink/strategies",
        json={"name": "Default Strategy", "maxQps": 10, "concurrency": 10},
    ).json()["data"]["strategy"]
    package = admin_client.post(
        "/api/hyperlink/data-packages",
        json={
            "name": "US Leads",
            "recipients": [
                {"phone": "+12025550120", "countryCode": "US", "variables": {"name": "A"}},
                {"phone": "+1 202 555 0120", "countryCode": "US", "variables": {"name": "duplicate"}},
                {"phone": "+12025550121", "countryCode": "US", "variables": {"name": "B"}},
            ],
        },
    ).json()["data"]["dataPackage"]
    assert package["recipientCount"] == 2
    task = admin_client.post(
        "/api/hyperlink/tasks",
        json={
            "name": "US Broadcast",
            "templateId": template["id"],
            "strategyId": strategy["id"],
            "dataPackageId": package["id"],
            "accountIds": [account_id],
            "channel": "facebook",
        },
    ).json()["data"]["task"]
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text
    result = started.json()["data"]["task"]
    assert result["status"] == "running"
    assert result["totalCount"] == 2
    assert result["queuedCount"] == 2
    process_task(task["id"])
    messages = admin_client.get(
        f"/api/personal-accounts/{account_id}/messages"
    ).json()["data"]["rows"]
    task_messages = [row for row in messages if row["requestId"].startswith(task["id"])]
    assert len(task_messages) == 2
    for row in task_messages:
        assert row["status"] == "queued"
        assert _gateway_event(admin_client, row["messageId"], account_id, "sent").status_code == 200
        assert _gateway_event(admin_client, row["messageId"], account_id, "delivered").status_code == 200
    result = admin_client.get(f"/api/hyperlink/tasks/{task['id']}").json()["data"]["task"]
    assert result["status"] == "completed"
    assert result["deliveredCount"] == 2
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    assert insight["totals"]["sent"] >= 2
    assert insight["totals"]["delivered"] >= 2
    assert any(
        row["sourceCountry"] == "US" and row["targetCountry"] == "US"
        for row in insight["rows"]
    )
    with SessionLocal() as db:
        stored_account = db.scalar(
            select(PersonalAccount).where(PersonalAccount.public_id == account_id)
        )
        stored_account.status = "reauth_required"
        db.commit()
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    us_row = next(row for row in insight["rows"] if row["sourceCountry"] == "US")
    assert us_row["abnormalAccounts"] == 1
    assert us_row["bannedAccounts"] == 0
    with SessionLocal() as db:
        stored_account = db.scalar(
            select(PersonalAccount).where(PersonalAccount.public_id == account_id)
        )
        stored_account.status = "restricted"
        db.commit()
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    us_row = next(row for row in insight["rows"] if row["sourceCountry"] == "US")
    assert us_row["bannedAccounts"] == 1
    assert us_row["banRate"] == 1.0


def test_landing_pairing_failure_keeps_retryable_account(
    admin_client: TestClient, monkeypatch
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]

    def fail_pair(*_args, **_kwargs):
        raise GatewayError("WhatsApp 网关请求失败（502）")

    monkeypatch.setattr(WaGatewayClient, "pair", fail_pair)
    failed = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456793",
            "visitorId": "landing-failure-visitor",
            "sessionToken": public_config["sessionToken"],
        },
    )
    assert failed.status_code == 502

    rows = admin_client.get(
        "/api/personal-accounts?keyword=4915123456793"
    ).json()["data"]
    assert rows["total"] == 1
    account = rows["rows"][0]
    assert account["status"] == "unpaired"
    assert account["validationStatus"] == "failed"
    assert account["lastError"] == "WhatsApp 网关请求失败（502）"


def test_legacy_unverified_landing_pairing_can_request_a_fresh_code(
    admin_client: TestClient,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    payload = {
        "phone": "+4915123456794",
        "visitorId": "legacy-pairing-retry-visitor",
        "sessionToken": public_config["sessionToken"],
    }

    first = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json=payload,
    )
    assert first.status_code == 200, first.text

    # Mock pairing deliberately leaves the same legacy shape that old
    # production releases persisted before a real connection was verified.
    stored = admin_client.get(
        "/api/personal-accounts?keyword=4915123456794"
    ).json()["data"]["rows"][0]
    assert stored["status"] == "linked_offline"
    assert stored["validationStatus"] == "validating"
    assert stored["lastConnectedAt"] is None

    retried = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json=payload,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["pairing"]["pairingCode"] == "0000-0000"


def test_public_pairing_status_never_treats_unverified_offline_as_success() -> None:
    from app.routers.promotion import _public_pairing_status

    now = utcnow()
    assert _public_pairing_status(
        state="linked_offline",
        gateway_pairing_status="reconnecting",
        verified=False,
        attempt_status="waiting_phone",
        expires_at=now + timedelta(minutes=3),
    ) == "reconnecting"
    assert _public_pairing_status(
        state="linked_offline",
        gateway_pairing_status="waiting_phone",
        verified=False,
        attempt_status="waiting_phone",
        expires_at=now - timedelta(seconds=1),
    ) == "expired"
    assert _public_pairing_status(
        state="linked_offline",
        gateway_pairing_status="waiting_phone",
        verified=True,
        attempt_status="waiting_phone",
        expires_at=now - timedelta(seconds=1),
    ) == "verified"


def test_public_pairing_attempt_can_be_cancelled_with_header_token(
    admin_client: TestClient,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    started = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456798",
            "visitorId": "pairing-cancel-visitor",
            "sessionToken": public_config["sessionToken"],
        },
    )
    assert started.status_code == 200, started.text
    pairing = started.json()["data"]["pairing"]
    assert pairing["statusTokenHeader"] == "X-Parloq-Pairing-Token"

    cancelled = admin_client.post(
        pairing["cancelUrl"],
        headers={"X-Parloq-Pairing-Token": pairing["statusToken"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"] == {
        "pairingStatus": "cancelled",
        "cancelled": True,
    }
    status = admin_client.get(
        pairing["statusUrl"],
        headers={"X-Parloq-Pairing-Token": pairing["statusToken"]},
    )
    assert status.status_code == 200, status.text
    assert status.json()["data"]["pairingStatus"] == "cancelled"
    assert status.json()["data"]["verified"] is False


def test_personal_account_create_rollback_and_bulk_state_sync(
    admin_client: TestClient, monkeypatch
) -> None:
    def fail_create(*_args, **_kwargs):
        raise GatewayError("gateway unavailable")

    monkeypatch.setattr(WaGatewayClient, "create", fail_create)
    failed = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Rollback", "phone": "+12025551991", "countryCode": "US"},
    )
    assert failed.status_code == 502
    rows = admin_client.get("/api/personal-accounts?keyword=12025551991").json()["data"]
    assert rows["total"] == 0

    monkeypatch.undo()
    created = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Sync State", "phone": "+12025551992", "countryCode": "US"},
    )
    assert created.status_code == 201
    account_id = created.json()["data"]["account"]["id"]
    monkeypatch.setattr(
        WaGatewayClient,
        "list",
        lambda _self: [{"id": account_id, "phoneE164": "+12025551992", "state": "restricted"}],
    )
    synced = admin_client.get("/api/personal-accounts?sync=true&pageSize=100")
    assert synced.status_code == 200
    row = next(item for item in synced.json()["data"]["rows"] if item["id"] == account_id)
    assert row["status"] == "restricted"


def test_structured_payload_rejects_executable_html(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/hyperlink/materials",
        json={"name": "Unsafe", "type": "text", "contentJson": {"html": "<script>alert(1)</script>"}},
    )
    assert response.status_code == 422
