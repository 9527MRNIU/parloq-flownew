from __future__ import annotations

import io
import hashlib
import hmac
import json
import re
import zipfile
from datetime import timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AccountLifecycleEvent,
    AccountMetadataSyncJob,
    AccountPairingAttempt,
    AccountProxyBinding,
    MessageDelivery,
    PersonalAccount,
    PromotionEvent,
    PromotionLead,
    PromotionVisitor,
)
from app.routers import promotion as promotion_router
from app.routers.promotion import MAX_VIDEO_FILE, _localize_template_html
from app.routers.promotion_monitoring import _device_summary
from app.security import utcnow
from app.services.request_network import RequestNetwork
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.services.account_metadata_sync import (
    process_pending_account_metadata_sync_jobs,
)
from app.task_worker import process_task, recover_running_tasks


def _device_fingerprint() -> str:
    return "0ef8bdbc97de077c45a46358ecc4ba42"


def _zip(files: dict[str, str | bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_promotion_monitoring_device_summary_includes_readable_versions() -> None:
    ios = _device_summary(
        {
            "requestContext": {
                "userAgent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
                    "Mobile/15E148 Safari/604.1"
                ),
            },
            "clientContext": {"viewport": [390, 844]},
        }
    )
    assert ios["browser"] == "Safari"
    assert ios["browserVersion"] == "18.6"
    assert ios["system"] == "iOS"
    assert ios["systemVersion"] == "18.6"
    assert ios["viewport"] == [390, 844]

    macos = _device_summary(
        {
            "requestContext": {
                "userAgent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                )
            }
        }
    )
    assert macos["browser"] == "Chrome"
    assert macos["browserVersion"] == "151.0.0.0"
    assert macos["system"] == "macOS"
    assert macos["systemVersion"] == "10.15.7"


def _v3_template_manifest(
    *, version: str = "3.0.0", supported_locales: list[str] | None = None
) -> dict:
    locales = supported_locales or ["en"]
    return {
        "schema": "promotion-template/v3",
        "version": version,
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
        "supportedLocales": locales,
        "i18n": {
            "mode": "bundled",
            "path": "locales/{locale}.json",
            "fallbackLocale": "en",
        },
    }


STANDARD_COMPONENTS_HTML = """<account-link-flow>
<account-link-locale-switcher></account-link-locale-switcher>
<phone-number-field></phone-number-field>
<account-link-submit></account-link-submit>
<pairing-code-panel></pairing-code-panel>
<app-launch-actions></app-launch-actions>
<account-link-status></account-link-status>
<account-initialization-status></account-initialization-status>
</account-link-flow>"""


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
    with SessionLocal() as db:
        if message_id.isdigit():
            delivery = db.get(MessageDelivery, int(message_id))
            assert delivery is not None
            message_id = delivery.public_id
        if account_id.isdigit():
            account = db.get(PersonalAccount, int(account_id))
            assert account is not None
            account_id = account.gateway_account_id
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
    provider_code: str | None = None,
    failure: dict | None = None,
):
    if account_id.isdigit():
        with SessionLocal() as db:
            account = db.get(PersonalAccount, int(account_id))
            assert account is not None
            account_id = account.gateway_account_id
    body = json.dumps(
        {
            "event": "account.state",
            "eventId": event_id,
            "accountId": account_id,
            "fromState": from_state,
            "toState": to_state,
            "reasonCategory": reason,
            "providerCode": (
                provider_code
                if provider_code is not None
                else "403" if to_state == "restricted" else None
            ),
            "failure": failure,
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
            select(PersonalAccount).where(PersonalAccount.id == int(account_id))
        )
        assert account is not None
        events = db.scalars(
            select(AccountLifecycleEvent).where(
                AccountLifecycleEvent.account_id == account.id
            )
        ).all()
        event_ids = {event.public_id for event in events}
        assert "ast_restricted_test" in event_ids
        assert "ast_stale_connected_test" in event_ids
        assert any(event_id.startswith("initial_") for event_id in event_ids)


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


def test_promotion_zip_channel_tracking_leads_and_insights(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        promotion_router,
        "resolve_request_network",
        lambda _request: RequestNetwork("2001:db8::25", "CA", "cloudflare"),
    )
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

    mp4_content = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"
    webm_content = b"\x1a\x45\xdf\xa3webm-demo-content"
    assert MAX_VIDEO_FILE == 50 * 1024 * 1024

    initial = _zip(
        {
            "index.html": (
                "<HTML><HEAD></HEAD><body>"
                f"{STANDARD_COMPONENTS_HTML}"
                '<script src="assets/account-link-elements.js"></script>'
                "</body></HTML>"
            ),
            "manifest.json": json.dumps(_v3_template_manifest()),
            "assets/account-link-elements.js": "window.testComponents = true;",
            "locales/en.json": "{}",
        }
    )
    imported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Vite Promotion Template"},
        files={"file": ("promotion.zip", initial, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    assert template["id"].isdecimal()
    assert "publicId" not in template
    assert template["manifest"]["schema"] == "promotion-template/v3"
    assert template["manifest"]["runtime"] == "promotion-browser-bridge/v2"
    assert template["manifest"]["capabilities"] == ["phone-pairing"]
    assert template["defaultLocale"] == "en"
    assert template["supportedLocales"] == ["en"]
    assert template["qualityReport"]["status"] == "warnings"
    assert {
        "viewport_missing",
    } <= {
        warning["code"] for warning in template["qualityReport"]["warnings"]
    }

    manifest = _v3_template_manifest(
        version="2", supported_locales=["en", "de", "ar", "fr"]
    )
    replacement = _zip(
        {
            "dist/index.html": f'<html lang="en"><head><title>Hello</title><link rel="stylesheet" href="assets/app.css"><script type="module" src="assets/app.js"></script></head><body><h1 data-copy="title">Hello</h1><input data-copy-placeholder="phonePlaceholder" placeholder="12025550123"><img src="/assets/logo.png">{STANDARD_COMPONENTS_HTML}<script src="assets/account-link-elements.js"></script></body></html>',
            "dist/manifest.json": json.dumps(manifest),
            "dist/assets/app.js": "window.templateLoaded=true",
            "dist/assets/app.css": "body{color:#123456}",
            "dist/assets/account-link-elements.js": "window.testComponents = true;",
            "dist/assets/logo.png": "demo",
            "dist/assets/hero.mp4": mp4_content,
            "dist/assets/loop.webm": webm_content,
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
    assert "frame-ancestors http://testserver" in preview.headers[
        "content-security-policy"
    ]
    assert "allow-same-origin" not in preview.headers["content-security-policy"]
    assert "connect-src http://testserver" in preview.headers["content-security-policy"]
    assert "media-src http://testserver data: blob:" in preview.headers[
        "content-security-policy"
    ]
    assert '"previewMode": true' in preview.text
    assert '"previewDevice": "desktop"' in preview.text
    assert "promotionPreviewState='code_issued'" in preview.text
    assert "promotion-preview:set-state" in preview.text
    assert "promotion-preview:pairing-started" in preview.text
    assert "promotionPreviewPolls" not in preview.text
    assert "nextPollAfterMs:1000" in preview.text
    assert '"templatePolicy": {' in preview.text
    assert '"deviceSignals"' not in preview.text
    assert "window.PromotionBridge" in preview.text
    assert 'addEventListener("contextmenu"' in preview.text
    assert 'e.key==="F12"' in preview.text
    automatic_preview = admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview",
        headers={"Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8"},
    )
    assert automatic_preview.status_code == 200
    assert automatic_preview.headers["content-language"] == "ar"
    assert '<html lang="ar" dir="rtl">' in automatic_preview.text
    assert "تابع برقم هاتفك" in automatic_preview.text
    german_preview = admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview?lang=de",
        headers={"Accept-Language": "ar"},
    )
    assert german_preview.status_code == 200
    assert german_preview.headers["content-language"] == "de"
    assert '<html lang="de" dir="ltr">' in german_preview.text
    assert "Hallo" in german_preview.text
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
    signed_video = admin_client.get(
        f"{signed_asset_root}assets/hero.mp4",
        headers={"Range": "bytes=4-11"},
    )
    assert signed_video.status_code == 206
    assert signed_video.content == mp4_content[4:12]
    assert signed_video.headers["content-type"].startswith("video/mp4")
    assert signed_video.headers["accept-ranges"] == "bytes"
    assert signed_video.headers["content-range"] == f"bytes 4-11/{len(mp4_content)}"
    invalid_video_range = admin_client.get(
        f"{signed_asset_root}assets/hero.mp4",
        headers={"Range": "bytes=999-"},
    )
    assert invalid_video_range.status_code == 416
    assert invalid_video_range.headers["content-range"] == f"bytes */{len(mp4_content)}"
    signed_webm = admin_client.get(f"{signed_asset_root}assets/loop.webm")
    assert signed_webm.status_code == 200
    assert signed_webm.content == webm_content
    assert signed_webm.headers["content-type"].startswith("video/webm")
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

    landing_group = admin_client.post(
        "/api/account-groups", json={"name": "Germany Landing Accounts"}
    )
    assert landing_group.status_code == 201, landing_group.text
    landing_group_id = landing_group.json()["data"]["group"]["id"]
    channel = admin_client.post(
        "/api/promotion/channels",
        json={
            "type": "facebook",
            "name": "Germany Facebook",
            "countryCode": "DE",
            "templateId": template["id"],
            "domainId": domain_id,
            "pixelId": pixel_id,
            "accountGroupId": landing_group_id,
            "slug": "de-facebook-demo",
            "status": "active",
            "localeMode": "auto",
            "launchAt": "2099-01-01T00:00:00Z",
        },
    )
    assert channel.status_code == 201, channel.text
    channel_row = channel.json()["data"]["channel"]
    channel_id = channel_row["id"]
    assert channel_id.isdecimal()
    assert channel_row["templateId"] == template["id"]
    assert channel_row["domainId"] == domain_id
    assert channel_row["pixelId"] == pixel_id
    assert channel_row["accountGroupId"] == landing_group_id
    assert channel_row["accountGroupName"] == "Germany Landing Accounts"
    assert "launchAt" not in channel_row
    assert not any(key.endswith("PublicId") for key in channel_row)
    fixed_locale = admin_client.patch(
        f"/api/promotion/channels/{channel_id}",
        json={"localeMode": "fixed", "locale": "de"},
    )
    assert fixed_locale.status_code == 422

    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo",
        headers={"Accept-Language": "de-DE,de;q=0.9"},
    )
    assert public_config.status_code == 200
    config = public_config.json()["data"]
    assert config["resolvedLocale"] == "de"
    assert config["countryCode"] == "DE"
    automatic_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo",
        headers={"Accept-Language": "ja-JP;q=0.9,ar-SA;q=0.8"},
    )
    assert automatic_config.status_code == 200
    assert automatic_config.json()["data"]["resolvedLocale"] == "ar"
    assert "sessionToken" not in config
    assert "sessionExpiresIn" not in config
    invalid = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json={
            "eventType": "page_view",
            "idempotencyKey": "missing-visitor-event",
        },
    )
    assert invalid.status_code == 422

    page_view = {
        "eventType": "page_view",
        "deviceFingerprint": _device_fingerprint(),
        "metadata": {
            "requestContext": {"userAgent": "forged-client-ua"},
            "clientContext": {
                "timeZone": "America/Toronto",
                "viewport": [390, 844],
                "screen": [390, 844],
                "pixelRatio": 3,
                "touchPoints": 5,
            }
        },
    }
    page_view_response = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json=page_view,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept-Language": "en-CA,en;q=0.9",
        },
    )
    assert page_view_response.status_code == 200
    delayed_page_view = {
        "eventType": "page_view",
        "deviceFingerprint": _device_fingerprint(),
    }
    assert admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json=delayed_page_view,
    ).status_code == 200
    from app.services.promotion_event_rate_limits import (
        PromotionEventRateLimitDecision,
    )

    with monkeypatch.context() as context:
        context.setattr(
            "app.routers.promotion.consume_promotion_event_rate_limits",
            lambda *_args, **_kwargs: PromotionEventRateLimitDecision(
                allowed=False,
                retry_after_seconds=17,
                policy_key="sessionReports",
                limit=1,
            ),
        )
        limited_report = admin_client.post(
            "/api/public/promotion/channels/de-facebook-demo/events",
            json={
                **page_view,
            },
        )
    assert limited_report.status_code == 429
    assert limited_report.headers["retry-after"] == "17"
    assert limited_report.json()["error"]["code"] == "report_rate_limited"
    client_phone_submit = {
        "eventType": "phone_submit",
        "idempotencyKey": "phone-lead-event-0001",
        "visitorId": "visitor-fingerprint-0001",
        "phone": "+49 151 23456789",
        "deviceFingerprint": _device_fingerprint(),
    }
    rejected_client_submit = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json=client_phone_submit,
    )
    assert rejected_client_submit.status_code == 422
    server_submit = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+49 151 23456789",
            "deviceFingerprint": _device_fingerprint(),
            "metadata": {
                "form": "primary",
                "clientContext": {"viewport": [390, 844]},
            },
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept-Language": "en-CA,en;q=0.9",
        },
    )
    assert server_submit.status_code == 409, server_submit.text
    assert server_submit.json()["error"]["code"] == "connection_route_unavailable"
    with SessionLocal() as db:
        fingerprint_event = db.scalar(
            select(PromotionEvent)
            .where(PromotionEvent.event_type == "phone_submit")
            .order_by(PromotionEvent.created_at.desc())
        )
        assert fingerprint_event is not None
        promotion_visitor = db.get(
            PromotionVisitor, fingerprint_event.promotion_visitor_id
        )
        assert promotion_visitor is not None
        assert len(promotion_visitor.fingerprint_hash) == 64
        assert promotion_visitor.fingerprint_version == "thumbmarkjs/1.10.1"
        assert promotion_visitor.fingerprint_quality == "high"
        promotion_visitor_id = str(promotion_visitor.id)
        assert fingerprint_event.source_ip == "2001:db8::25"
        assert fingerprint_event.visitor_country_code == "CA"
        assert fingerprint_event.network_source == "cloudflare"
        assert fingerprint_event.metadata_json["submissionSource"] == "pairing_start"
        assert fingerprint_event.metadata_json["form"] == "primary"
        assert fingerprint_event.request_context_json["userAgent"].endswith(
            "Mobile/15E148 Safari/604.1"
        )
        assert fingerprint_event.request_context_json["language"] == "en-CA"
        assert "requestContext" not in fingerprint_event.metadata_json
    leads = admin_client.get(f"/api/promotion/channels/{channel_id}/leads").json()["data"]
    assert leads["total"] == 1
    assert leads["rows"][0]["phone"] == "+4915123456789"
    stats = admin_client.get(f"/api/promotion/channels/{channel_id}/stats").json()["data"]
    assert stats["totals"]["pageView"] == 2
    assert stats["totals"]["uv"] == 1
    assert stats["totals"]["browserUv"] == 1
    assert stats["totals"]["fingerprintUv"] == 1
    assert stats["totals"]["fingerprintCoverage"] == 2
    assert stats["totals"]["fingerprintCoverageRate"] == 1
    assert stats["totals"]["phoneSubmit"] == 1
    monitored = admin_client.get(
        f"/api/promotion/monitoring/records?channelId={channel_id}"
        "&eventType=phone_submit&visitorCountryCode=CA"
    )
    assert monitored.status_code == 200, monitored.text
    monitored_data = monitored.json()["data"]
    assert monitored_data["total"] == 1
    monitored_record = monitored_data["rows"][0]
    assert monitored_record["source"] == "server"
    assert monitored_record["eventType"] == "phone_submit"
    assert monitored_record["visitorId"] == promotion_visitor_id
    assert monitored_record["sourceIp"] == "2001:db8::25"
    assert monitored_record["visitorCountryCode"] == "CA"
    assert monitored_record["networkSource"] == "cloudflare"
    assert monitored_record["device"]["browser"] == "Safari"
    assert monitored_record["device"]["browserVersion"] == "18.6"
    assert monitored_record["device"]["viewport"] == [390, 844]
    assert monitored_record["id"].isdigit()
    record_detail = admin_client.get(
        "/api/promotion/monitoring/records/server/"
        f"{monitored_record['id']}"
    )
    assert record_detail.status_code == 200, record_detail.text
    detail = record_detail.json()["data"]["record"]
    assert detail["visitorId"] == promotion_visitor_id
    assert detail["sourceIp"] == "2001:db8::25"
    assert detail["visitorCountryCode"] == "CA"
    assert detail["networkSource"] == "cloudflare"
    assert detail["requestContext"]["language"] == "en-CA"
    assert detail["clientContext"]["viewport"] == [390, 844]
    assert detail["metadata"]["submissionSource"] == "pairing_start"
    monitoring_options = admin_client.get("/api/promotion/monitoring/options")
    assert monitoring_options.status_code == 200
    assert "CA" in monitoring_options.json()["data"]["visitorCountries"]
    policy = admin_client.patch(
        "/api/promotion/template-policy",
        json={
            "protectionMode": "strict",
            "devtoolsAction": "blank",
            "lockViewportZoom": True,
        },
    )
    assert policy.status_code == 200, policy.text
    render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render",
        headers={"Accept-Language": "de-DE,de;q=0.9"},
    )
    assert "promotion-runtime-config" in render.text
    assert "parloq" not in render.text.lower()
    tracker_url_match = re.search(
        r'src="(?P<url>/api/public/promotion/tracker\.js\?v=[0-9a-f]{12})"',
        render.text,
    )
    guard_url_match = re.search(
        r'src="(?P<url>/api/public/promotion/guard\.js\?v=[0-9a-f]{12})"',
        render.text,
    )
    assert tracker_url_match is not None
    assert guard_url_match is not None
    assert '<base href="/api/public/promotion/channels/de-facebook-demo/assets/">' in render.text
    assert render.text.index("<base ") < render.text.index("<link ")
    assert render.text.index("<base ") < render.text.index('src="assets/app.js"')
    assert '"pixelDatasetId": "promo-dataset-001"' in render.text
    assert '"templatePolicy": {' in render.text
    assert '"protectionMode": "strict"' in render.text
    assert '"devtoolsAction": "blank"' in render.text
    assert '"deviceSignals"' not in render.text
    assert render.headers["content-language"] == "de"
    assert '<html lang="de" dir="ltr">' in render.text
    assert "<title>Hallo</title>" in render.text
    assert '<h1 data-copy="title">Hallo</h1>' in render.text
    assert 'placeholder="4915123456789"' in render.text
    assert '"localizedCopy": {"title": "Hallo"' in render.text
    assert "maximum-scale=1,user-scalable=no" in render.text
    assert "media-src http://testserver data: blob:" in render.headers[
        "content-security-policy"
    ]
    assert 'src="assets/app.js"' in render.text
    assert "/api/public/promotion/channels/de-facebook-demo/assets/assets/logo.png" in render.text
    assert "/assets/assets/assets/" not in render.text
    rtl_render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render?lang=de",
        headers={"Accept-Language": "ar-SA,ar;q=0.9"},
    )
    assert rtl_render.headers["content-language"] == "ar"
    assert '<html lang="ar" dir="rtl">' in rtl_render.text
    assert "<title>تابع برقم هاتفك</title>" in rtl_render.text
    automatic_render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render",
        headers={"Accept-Language": "ja-JP;q=0.9,ar-SA;q=0.8"},
    )
    assert automatic_render.headers["content-language"] == "ar"
    assert '<html lang="ar" dir="rtl">' in automatic_render.text
    assert '"resolvedLocale": "ar"' in automatic_render.text
    fallback_render = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/render",
        headers={"Accept-Language": "fr-FR,fr;q=0.9"},
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
    public_video = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/assets/assets/hero.mp4",
        headers={"Range": "bytes=-8"},
    )
    assert public_video.status_code == 206
    assert public_video.content == mp4_content[-8:]
    assert public_video.headers["accept-ranges"] == "bytes"
    assert public_video.headers["content-range"] == (
        f"bytes {len(mp4_content) - 8}-{len(mp4_content) - 1}/{len(mp4_content)}"
    )
    locale_asset = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo/assets/locales/de.json"
    )
    assert locale_asset.status_code == 200
    assert locale_asset.json()["title"] == "Hallo"
    tracker = admin_client.get("/api/public/promotion/tracker.js")
    assert tracker.headers["cache-control"] == "no-store"
    assert "connect.facebook.net/en_US/fbevents.js" in tracker.text
    assert "meta-domain-unavailable" in render.text
    assert "is unavailable" in tracker.text
    assert "getPairingStatus" in tracker.text
    assert "pairingStartUrl" in tracker.text
    assert "pairing_start_failed" in tracker.text
    assert "form[data-promotion-manual]" in tracker.text
    assert "parloq" not in tracker.text.lower()
    assert "page_view" in tracker.text
    assert "inspection_detected" in tracker.text
    assert '"1.10.1"' in tracker.text
    assert "deviceFingerprint" in tracker.text
    assert "deviceToken" not in tracker.text
    assert "sessionToken" not in tracker.text
    assert "clientContext" in tracker.text
    assert '"_fp"' in tracker.text
    assert "OfflineAudioContext" in tracker.text
    assert "device-fingerprint/v1" not in tracker.text
    assert tracker.headers["x-content-type-options"] == "nosniff"
    versioned_tracker = admin_client.get(tracker_url_match.group("url"))
    assert versioned_tracker.content == tracker.content
    assert tracker_url_match.group("url").endswith(
        hashlib.sha256(tracker.content).hexdigest()[:12]
    )
    assert versioned_tracker.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
    stale_tracker = admin_client.get(
        "/api/public/promotion/tracker.js?v=000000000000"
    )
    assert stale_tracker.headers["cache-control"] == "no-store"
    guard = admin_client.get("/api/public/promotion/guard.js")
    assert guard.status_code == 200
    assert guard.headers["cache-control"] == "no-store"
    assert 'addEventListener("contextmenu"' in guard.text
    assert 'e.key==="F12"' in guard.text
    assert 'input[type="tel"]' in guard.text
    assert 'replace(/\\+/g,"")' in guard.text
    assert 'window-gap' not in guard.text
    assert "outerWidth" not in guard.text
    assert "outerHeight" not in guard.text
    assert 'debugger-delay' in guard.text
    assert "parloq" not in guard.text.lower()
    versioned_guard = admin_client.get(guard_url_match.group("url"))
    assert versioned_guard.content == guard.content
    assert guard_url_match.group("url").endswith(
        hashlib.sha256(guard.content).hexdigest()[:12]
    )
    assert versioned_guard.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )

    inspection = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        content=json.dumps(
            {
                "eventType": "inspection_detected",
                "deviceFingerprint": _device_fingerprint(),
                "metadata": {"reason": "mobile-console", "mode": "enhanced"},
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


def test_promotion_template_enforces_video_specific_file_limit(
    admin_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(promotion_router, "MAX_VIDEO_FILE", 32)
    package = _zip(
        {
            "index.html": (
                f"<html><body>{STANDARD_COMPONENTS_HTML}"
                '<script src="assets/account-link-elements.js"></script>'
                '<video src="assets/too-large.mp4"></video></body></html>'
            ),
            "manifest.json": json.dumps(_v3_template_manifest()),
            "assets/account-link-elements.js": "window.testComponents = true;",
            "assets/too-large.mp4": b"0" * 33,
        }
    )
    rejected = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Oversized video template"},
        files={"file": ("oversized-video.zip", package, "application/zip")},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"].startswith("视频文件超过 ")
    assert rejected.json()["detail"].endswith("：assets/too-large.mp4")


def test_promotion_template_rejects_non_v3_contract_and_source_maps(
    admin_client: TestClient,
) -> None:
    unknown_schema = _zip(
        {
            "index.html": '<form><input type="tel"></form>',
            "manifest.json": json.dumps(
                {
                    "schema": "promotion-template/v2",
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

    missing_components = _zip(
        {
            "index.html": "<!doctype html><html><body></body></html>",
            "manifest.json": json.dumps(
                {
                    **_v3_template_manifest(),
                    "components": None,
                }
            ),
        }
    )
    rejected_v2 = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Missing component kit"},
        files={
            "file": (
                "missing-components.zip",
                missing_components,
                "application/zip",
            )
        },
    )
    assert rejected_v2.status_code == 422
    assert "components" in rejected_v2.json()["detail"]

    legacy_manifest = _v3_template_manifest()
    legacy_manifest["requirements"]["componentKit"] = "account-link-elements/v1"
    legacy_component_injection = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Legacy component injection"},
        files={
            "file": (
                "legacy-component-injection.zip",
                _zip(
                    {
                        "index.html": '<html><body><script src="assets/account-link-elements.js"></script></body></html>',
                        "manifest.json": json.dumps(legacy_manifest),
                        "assets/account-link-elements.js": "window.testComponents = true;",
                        "locales/en.json": "{}",
                    }
                ),
                "application/zip",
            )
        },
    )
    assert legacy_component_injection.status_code == 422
    assert "不再支持平台注入" in legacy_component_injection.json()["detail"]

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


def test_self_contained_v3_template_imports_without_platform_component_injection(
    admin_client: TestClient,
) -> None:
    assert admin_client.get(
        "/api/promotion/template-kits/account-link-elements-v1.zip"
    ).status_code == 404
    assert admin_client.get(
        "/api/public/promotion/account-link-elements.js"
    ).status_code == 404

    package = _zip(
        {
            "index.html": (
                '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
                f"{STANDARD_COMPONENTS_HTML}"
                '<script src="assets/account-link-elements.js"></script>'
                "</body></html>"
            ),
            "manifest.json": json.dumps(_v3_template_manifest(version="3.1.0")),
            "assets/account-link-elements.js": "window.bundledComponentMarker = true;",
            "locales/en.json": "{}",
        }
    )

    imported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Self-contained account linking template"},
        files={
            "file": (
                "0001-account-link-template-3.1.0.zip",
                package,
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    assert template["manifest"]["components"] == {
        "contract": "account-link-elements/v1",
        "entry": "assets/account-link-elements.js",
    }
    assert template["qualityReport"]["status"] == "passed"

    preview = admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview"
    )
    assert preview.status_code == 200
    assert 'src="assets/account-link-elements.js"' in preview.text
    assert "/api/public/promotion/account-link-elements.js" not in preview.text
    assert "<account-link-flow" in preview.text

    mobile_preview = admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview?device=mobile"
    )
    assert mobile_preview.status_code == 200
    assert '"previewDevice": "mobile"' in mobile_preview.text
    assert admin_client.get(
        f"/api/promotion/templates/{template['id']}/preview?device=watch"
    ).status_code == 422


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

    def create_after_account_commit(self, account_id, phone, proxy_url, **kwargs):
        with SessionLocal() as independent_db:
            observed_persisted_account[account_id] = (
                independent_db.scalar(
                    select(PersonalAccount).where(
                        PersonalAccount.public_id == account_id
                    )
                )
                is not None
            )
        return original_create(self, account_id, phone, proxy_url, **kwargs)

    monkeypatch.setattr(WaGatewayClient, "create", create_after_account_commit)
    landing_group = next(
        row
        for row in admin_client.get("/api/account-groups").json()["data"]["rows"]
        if row["name"] == "Germany Landing Accounts"
    )
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    fingerprint_event = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/events",
        json={
            "eventType": "page_view",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert fingerprint_event.status_code == 200, fingerprint_event.text
    landing_pair = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456790",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert landing_pair.status_code == 200, landing_pair.text
    pairing = landing_pair.json()["data"]["pairing"]
    status_account_id = pairing["statusUrl"].split("/")[-2]
    assert status_account_id.isdigit()
    with SessionLocal() as db:
        status_account = db.get(PersonalAccount, int(status_account_id))
        assert status_account is not None
        assert observed_persisted_account[status_account.gateway_account_id] is True
        attempt = db.get(AccountPairingAttempt, int(pairing["attemptId"]))
        assert attempt is not None
        original_protocol_id = status_account.protocol_id
        assert attempt.protocol_node_id == original_protocol_id
        assert attempt.route_version >= 1
        assert attempt.sync_policy_json["avatar"] is True
        visitor = db.get(PromotionVisitor, attempt.promotion_visitor_id)
        assert visitor is not None
        assert len(visitor.fingerprint_hash) == 64
        assert visitor.fingerprint_version == "thumbmarkjs/1.10.1"
        assert visitor.fingerprint_quality == "high"
        pairing_visitor_id = str(visitor.id)
    monitored_pairing = admin_client.get(
        "/api/promotion/monitoring/records"
        f"?keyword={pairing_visitor_id}&eventType=phone_submit"
    )
    assert monitored_pairing.status_code == 200, monitored_pairing.text
    pairing_records = monitored_pairing.json()["data"]
    assert pairing_records["total"] >= 1
    assert pairing_records["rows"][0]["source"] == "server"
    assert pairing["pairingCode"] == "0000-0000"
    pairing_preflight = admin_client.options(
        pairing["statusUrl"],
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert pairing_preflight.status_code == 204
    assert pairing_preflight.headers["access-control-allow-origin"] == "null"
    assert (
        pairing_preflight.headers["access-control-allow-headers"]
        == "Authorization"
    )
    unrelated_preflight = admin_client.options(
        "/api/users",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert unrelated_preflight.status_code == 400
    changed_group = admin_client.post(
        "/api/account-groups", json={"name": "Future Germany Landing Accounts"}
    ).json()["data"]["group"]
    future_protocol = admin_client.post(
        "/api/protocol-nodes",
        json={"name": "Future Germany protocol"},
    ).json()["data"]["protocol"]
    changed_channel = admin_client.patch(
        f"/api/promotion/channels/{public_config['channel']['id']}",
        json={
            "accountGroupId": changed_group["id"],
            "protocolNodeId": future_protocol["id"],
            "protocolPoolId": None,
        },
    )
    assert changed_channel.status_code == 200, changed_channel.text
    landing_status = admin_client.get(
        pairing["statusUrl"],
        headers={
            "Origin": "null",
            "Authorization": f"Bearer {pairing['statusToken']}",
        },
    )
    assert landing_status.status_code == 200
    assert landing_status.headers["access-control-allow-origin"] == "null"
    status_data = landing_status.json()["data"]
    assert status_data["state"] == "ready"
    assert status_data["accountState"] == "linked_offline"
    assert status_data["pairingStatus"] == "verified"
    assert status_data["verified"] is True
    assert status_data["initializationStatus"] == "pending"
    assert status_data["attemptId"] == pairing["attemptId"]
    landing_account = admin_client.get(
        "/api/personal-accounts?keyword=4915123456790"
    ).json()["data"]["rows"][0]
    assert landing_account["source"] == "landing_page"
    assert landing_account["sourceRefId"] == public_config["channel"]["id"]
    assert landing_account["validationStatus"] == "ready"
    assert landing_account["group"] == {
        "id": landing_group["id"],
        "name": "Germany Landing Accounts",
    }
    with SessionLocal() as db:
        stored_after_switch = db.get(PersonalAccount, int(status_account_id))
        attempt_after_switch = db.get(
            AccountPairingAttempt, int(pairing["attemptId"])
        )
        assert stored_after_switch.protocol_id == original_protocol_id
        assert attempt_after_switch.protocol_node_id == original_protocol_id
        accounts_before_repeat = len(
            db.scalars(
                select(PersonalAccount).where(
                    PersonalAccount.phone_e164 == "+4915123456790"
                )
            ).all()
        )
        attempts_before_repeat = len(
            db.scalars(
                select(AccountPairingAttempt).where(
                    AccountPairingAttempt.account_id == stored_after_switch.id
                )
            ).all()
        )

    repeated_pairing = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456790",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert repeated_pairing.status_code == 409, repeated_pairing.text
    assert repeated_pairing.json() == {
        "error": {
            "code": "account_already_linked",
            "message": "该号码已经绑定并可用，无需重复绑定",
            "retryable": False,
        }
    }
    with SessionLocal() as db:
        repeated_account = db.get(PersonalAccount, int(status_account_id))
        assert repeated_account is not None
        assert (
            len(
                db.scalars(
                    select(PersonalAccount).where(
                        PersonalAccount.phone_e164 == "+4915123456790"
                    )
                ).all()
            )
            == accounts_before_repeat
        )
        assert (
            len(
                db.scalars(
                    select(AccountPairingAttempt).where(
                        AccountPairingAttempt.account_id == repeated_account.id
                    )
                ).all()
            )
            == attempts_before_repeat
        )
    account = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "US Sender",
            "phone": "+12025550111",
            "countryCode": "US",
            "proxyId": proxy_id,
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
    assert delivery["messageId"].isdigit()
    assert "publicId" not in delivery
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
        "/api/materials",
        json={"name": "Text CTA", "type": "text", "contentJson": {"text": "offer"}},
    ).json()["data"]["material"]
    assert any(
        row["id"] == material["id"]
        for row in admin_client.get("/api/hyperlink/materials").json()["data"]["rows"]
    )
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
    sender_group = admin_client.post(
        "/api/account-groups", json={"name": "US Broadcast Senders"}
    ).json()["data"]["group"]
    assert admin_client.patch(
        f"/api/personal-accounts/{account_id}",
        json={"groupId": sender_group["id"]},
    ).status_code == 200
    task = admin_client.post(
        "/api/hyperlink/tasks",
        json={
            "name": "US Broadcast",
            "templateId": template["id"],
            "strategyId": strategy["id"],
            "dataPackageId": package["id"],
            "accountGroupId": sender_group["id"],
            "channel": "facebook",
        },
    ).json()["data"]["task"]
    started = admin_client.post(f"/api/hyperlink/tasks/{task['id']}/start")
    assert started.status_code == 202, started.text
    result = started.json()["data"]["task"]
    assert result["status"] == "running"
    assert result["totalCount"] == 2
    assert result["queuedCount"] == 2
    assert result["templateName"] == "Offer Template"
    assert result["templateContent"]["body"]["text"] == "Hello {{name}}"
    assert result["submissionStats"] == {
        "total": 2,
        "waiting": 2,
        "submitting": 0,
        "accepted": 0,
        "failed": 0,
        "reconciling": 0,
        "cancelled": 0,
        "skipped": 0,
    }
    mutated = admin_client.patch(
        f"/api/hyperlink/templates/{template['id']}",
        json={"name": "Changed after task start"},
    )
    assert mutated.status_code == 200, mutated.text
    frozen = admin_client.get(
        f"/api/hyperlink/tasks/{task['id']}"
    ).json()["data"]["task"]
    assert frozen["templateName"] == "Offer Template"
    assert frozen["templateContent"]["body"]["text"] == "Hello {{name}}"
    task_id = task["id"]
    process_task(task_id)
    submitted = admin_client.get(
        f"/api/hyperlink/tasks/{task['id']}"
    ).json()["data"]["task"]
    assert submitted["status"] == "running"
    assert submitted["submissionStats"] == {
        "total": 2,
        "waiting": 0,
        "submitting": 0,
        "accepted": 2,
        "failed": 0,
        "reconciling": 0,
        "cancelled": 0,
        "skipped": 0,
    }
    assert submitted["sendStats"] == {"sent": 0, "delivered": 0, "failed": 0}
    messages = admin_client.get(
        f"/api/personal-accounts/{account_id}/messages"
    ).json()["data"]["rows"]
    task_messages = [row for row in messages if row["requestId"].startswith(task_id)]
    assert len(task_messages) == 2
    for row in task_messages:
        assert row["status"] == "queued"
        assert _gateway_event(admin_client, row["messageId"], account_id, "sent").status_code == 200
        assert _gateway_event(admin_client, row["messageId"], account_id, "delivered").status_code == 200
    result = admin_client.get(f"/api/hyperlink/tasks/{task['id']}").json()["data"]["task"]
    assert result["status"] == "completed"
    assert result["deliveredCount"] == 2
    assert result["submissionStats"]["accepted"] == 2
    assert result["sendStats"] == {"sent": 2, "delivered": 2, "failed": 0}
    recovered: list[str] = []
    monkeypatch.setattr(
        "app.task_worker.enqueue_hyperlink_task",
        lambda queued_task_id: recovered.append(queued_task_id) or True,
    )
    recover_running_tasks()
    assert task_id not in recovered
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    assert insight["totals"]["sent"] >= 2
    assert insight["totals"]["delivered"] >= 2
    assert any(
        row["sourceCountry"] == "US" and row["targetCountry"] == "US"
        for row in insight["rows"]
    )
    with SessionLocal() as db:
        stored_account = db.scalar(
            select(PersonalAccount).where(PersonalAccount.id == int(account_id))
        )
        stored_account.status = "reauth_required"
        db.commit()
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    us_row = next(row for row in insight["rows"] if row["sourceCountry"] == "US")
    assert us_row["abnormalAccounts"] == 1
    assert us_row["bannedAccounts"] == 0
    with SessionLocal() as db:
        stored_account = db.scalar(
            select(PersonalAccount).where(PersonalAccount.id == int(account_id))
        )
        stored_account.status = "restricted"
        db.commit()
    insight = admin_client.get("/api/hyperlink/market-insights").json()["data"]
    us_row = next(row for row in insight["rows"] if row["sourceCountry"] == "US")
    assert us_row["bannedAccounts"] == 1
    assert us_row["banRate"] == round(1 / us_row["accountCount"], 6)


def test_landing_pairing_failure_stays_in_intake_records(
    admin_client: TestClient, monkeypatch
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]

    failure_detail = {
        "code": "proxy_authentication_failed",
        "title": "代理认证失败",
        "message": "账号连接线路拒绝了当前认证信息。",
        "suggestion": "请检查或更换绑定代理后重新获取配对码。",
        "stage": "connection_route",
        "retryable": True,
        "technicalMessage": "Socks5 Authentication failed",
    }

    def fail_pair(*_args, **_kwargs):
        raise GatewayError(
            "WhatsApp 网关请求失败（502）",
            failure_detail=failure_detail,
        )

    monkeypatch.setattr(
        promotion_router,
        "resolve_request_network",
        lambda _request: RequestNetwork("203.0.113.25", "DE", "cloudflare"),
    )
    monkeypatch.setattr(WaGatewayClient, "pair", fail_pair)
    failed = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456793",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert failed.status_code == 502
    assert failed.json() == {
        "error": {
            "code": "gateway_failed",
            "message": "暂时无法连接账号服务，请稍后重试",
            "retryable": True,
        }
    }

    rows = admin_client.get(
        "/api/personal-accounts?keyword=4915123456793"
    ).json()["data"]
    assert rows["total"] == 0
    intake = admin_client.get(
        "/api/personal-accounts/intake/attempts?keyword=4915123456793"
    ).json()["data"]
    assert intake["total"] == 1
    attempt = intake["rows"][0]
    assert attempt["status"] == "failed"
    assert attempt["failureReason"] == {
        "code": "gateway_failed",
        "label": "网关失败",
        "detailCode": "pairing_start_failed",
        "providerCode": None,
    }
    assert attempt["failureDetail"] == failure_detail
    assert attempt["account"]["admissionStatus"] == "abandoned"
    assert attempt["account"]["validationStatus"] == "failed"
    assert attempt["account"]["countryCode"] == "DE"
    assert attempt["visitorCountryCode"] == "DE"
    assert attempt["sourceIp"] == "203.0.113.25"
    assert attempt["networkSource"] == "cloudflare"
    assert attempt["publicId"]
    assert attempt["requestContext"]["requestMethod"] == "POST"
    assert attempt["requestContext"]["requestPath"].endswith(
        "/de-facebook-demo/pairing/start"
    )
    assert attempt["requestContext"]["sourceIp"] == "203.0.113.25"
    assert "authorization" not in {
        key.lower() for key in attempt["requestContext"]
    }
    assert attempt["channel"]["slug"] == "de-facebook-demo"
    assert attempt["landing"]["url"].endswith("/de-facebook-demo")
    assert attempt["template"]["id"].isdigit()
    assert attempt["template"]["name"]
    assert attempt["template"]["version"]
    with SessionLocal() as db:
        failure_event = db.scalar(
            select(PromotionEvent).where(
                PromotionEvent.idempotency_key
                == f"pairing_failed:attempt:{attempt['id']}"
            )
        )
        assert failure_event is not None
        assert failure_event.lead_id is not None
        assert failure_event.metadata_json["reasonCode"] == "gateway_failed"
        assert failure_event.metadata_json["detailCode"] == "pairing_start_failed"
        assert failure_event.metadata_json["stage"] == "pairing_start"
        assert failure_event.metadata_json["attemptId"] == attempt["id"]

    detail = admin_client.get(
        f"/api/promotion/monitoring/records/server/{failure_event.id}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["record"]["metadata"]["attemptId"] == (
        attempt["id"]
    )


def test_pre_attempt_protocol_failure_uses_promotion_event_ledger(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]

    def unavailable_protocol(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="协议池中没有可接入节点")

    monkeypatch.setattr(
        "app.services.protocol_nodes.resolve_channel_ingress_protocol",
        unavailable_protocol,
    )
    failed = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456801",
            "deviceFingerprint": "3ef8bdbc97de077c45a46358ecc4ba42",
        },
    )
    assert failed.status_code == 409, failed.text
    assert failed.json()["error"] == {
        "code": "protocol_unavailable",
        "message": "当前没有可用的协议节点，请稍后再试",
        "retryable": True,
    }

    with SessionLocal() as db:
        failure = db.scalar(
                select(PromotionEvent)
                .where(
                    PromotionEvent.event_type == "pairing_failed",
                    PromotionEvent.metadata_json["reasonCode"].as_string()
                    == "protocol_unavailable",
                )
            .order_by(PromotionEvent.created_at.desc())
        )
        assert failure is not None
        assert failure.metadata_json["reasonCode"] == "protocol_unavailable"
        assert failure.metadata_json["detailCode"] == "protocol_route_unavailable"
        assert failure.metadata_json["stage"] == "protocol_routing"
        assert (
            db.scalar(
                select(AccountPairingAttempt).where(
                    AccountPairingAttempt.promotion_visitor_id
                    == failure.promotion_visitor_id
                )
            )
            is None
        )

    stats = admin_client.get(
        f"/api/promotion/channels/{public_config['channel']['id']}/stats"
    )
    assert stats.status_code == 200, stats.text
    reasons = stats.json()["data"]["pairingFailures"]["reasons"]
    protocol_reason = next(
        reason for reason in reasons if reason["code"] == "protocol_unavailable"
    )
    assert protocol_reason["label"] == "协议节点不可用"
    assert protocol_reason["count"] >= 1


def test_invalid_phone_and_rate_limit_are_safe_recorded_failures(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    invalid_phone = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "not-a-phone",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert invalid_phone.status_code == 422, invalid_phone.text
    assert invalid_phone.json()["error"]["code"] == "invalid_phone"

    from app.services.pairing_rate_limits import PairingRateLimitDecision

    monkeypatch.setattr(
        "app.services.pairing_rate_limits.consume_pairing_rate_limits",
        lambda *_args, **_kwargs: PairingRateLimitDecision(
            allowed=False,
            retry_after_seconds=17,
            policy_key="visitorCheck",
            limit=5,
        ),
    )
    rate_limited = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456803",
            "deviceFingerprint": "1ef8bdbc97de077c45a46358ecc4ba42",
        },
    )
    assert rate_limited.status_code == 429, rate_limited.text
    assert rate_limited.json()["error"] == {
        "code": "rate_limited",
        "message": "绑定请求过于频繁，请稍后再试",
        "retryable": True,
        "retryAfterSeconds": 17,
    }
    assert rate_limited.headers["retry-after"] == "17"

    with SessionLocal() as db:
        failures = {
            event.metadata_json["reasonCode"]: event.metadata_json
            for event in db.scalars(
                select(PromotionEvent).where(
                    PromotionEvent.event_type == "pairing_failed",
                )
            ).all()
        }
    assert failures["invalid_phone"]["reasonCode"] == "invalid_phone"
    assert failures["rate_limited"]["reasonCode"] == "rate_limited"
    assert failures["rate_limited"]["policyKey"] == "visitorCheck"


def test_invalid_fingerprint_is_visible_only_in_promotion_monitoring(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        promotion_router,
        "resolve_request_network",
        lambda _request: RequestNetwork("203.0.113.26", "DE", "cloudflare"),
    )
    failed = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456804",
            "deviceFingerprint": "invalid-fingerprint",
            "metadata": {"componentKit": "account-link-elements/v1"},
        },
        headers={"user-agent": "Validation Failure Browser/1.0"},
    )
    assert failed.status_code == 422, failed.text
    assert failed.json()["error"] == {
        "code": "invalid_request",
        "message": "请求信息无效，请刷新页面后重试",
        "retryable": False,
    }

    with SessionLocal() as db:
        failure = db.scalar(
            select(PromotionEvent)
            .where(
                PromotionEvent.event_type == "pairing_failed",
                PromotionEvent.metadata_json["detailCode"].as_string()
                == "device_identity_invalid",
            )
            .order_by(PromotionEvent.created_at.desc())
        )
        assert failure is not None
        assert failure.promotion_visitor_id is None
        assert failure.source_ip == "203.0.113.26"
        assert failure.visitor_country_code == "DE"
        assert failure.request_context_json["userAgent"] == (
            "Validation Failure Browser/1.0"
        )
        assert failure.metadata_json["reasonCode"] == "invalid_request"
        assert failure.metadata_json["stage"] == "request_validation"
        assert failure.metadata_json["validationFields"] == [
            "deviceFingerprint"
        ]
        failure_id = str(failure.id)
        assert db.scalar(
            select(PersonalAccount).where(
                PersonalAccount.phone_e164 == "+4915123456804"
            )
        ) is None

    monitoring = admin_client.get(
        "/api/promotion/monitoring/records"
        "?eventType=pairing_failed&pageSize=100"
    )
    assert monitoring.status_code == 200, monitoring.text
    row = next(
        item
        for item in monitoring.json()["data"]["rows"]
        if item["id"] == failure_id
    )
    assert row["source"] == "server"
    assert row["eventType"] == "pairing_failed"
    assert row["failureLabel"] == "请求信息无效"
    assert row["visitorId"] is None
    assert row["sourceIp"] == "203.0.113.26"

    intake = admin_client.get(
        "/api/personal-accounts/intake/attempts?keyword=4915123456804"
    )
    assert intake.status_code == 200, intake.text
    assert intake.json()["data"]["total"] == 0


def test_channel_stats_combines_events_and_attempts_into_pairing_funnel(
    admin_client: TestClient,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    started = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456802",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert started.status_code == 200, started.text
    pairing = started.json()["data"]["pairing"]
    verified = admin_client.get(
        pairing["statusUrl"],
        headers={"Authorization": f"Bearer {pairing['statusToken']}"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["pairingStatus"] == "verified"

    stats = admin_client.get(
        f"/api/promotion/channels/{public_config['channel']['id']}/stats"
    )
    assert stats.status_code == 200, stats.text
    funnel = stats.json()["data"]["pairingFunnel"]["steps"]
    assert [step["key"] for step in funnel] == [
        "visitors",
        "phoneSubmitted",
        "checksPassed",
        "pairingStarted",
        "verified",
    ]
    counts = [step["count"] for step in funnel]
    assert counts == sorted(counts, reverse=True)
    assert counts[-1] >= 1
    assert all(0 <= step["visitorRate"] <= 1 for step in funnel)
    assert all(0 <= step["stepRate"] <= 1 for step in funnel)


def test_number_country_is_independent_from_channel_and_visit_country(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        promotion_router,
        "resolve_request_network",
        lambda _request: RequestNetwork("203.0.113.86", "US", "cloudflare"),
    )
    started = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+8613187071551",
            "deviceFingerprint": "6ef8bdbc97de077c45a46358ecc4ba42",
        },
    )
    assert started.status_code == 200, started.text
    pairing = started.json()["data"]["pairing"]
    verified = admin_client.get(
        pairing["statusUrl"],
        headers={"Authorization": f"Bearer {pairing['statusToken']}"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["pairingStatus"] == "verified"

    intake = admin_client.get(
        "/api/personal-accounts/intake/attempts?keyword=8613187071551"
    ).json()["data"]
    assert intake["total"] == 1
    assert intake["rows"][0]["account"]["countryCode"] == "CN"
    assert intake["rows"][0]["visitorCountryCode"] == "US"

    with SessionLocal() as db:
        lead = db.scalar(
            select(PromotionLead).where(
                PromotionLead.phone_e164 == "+8613187071551"
            )
        )
        assert lead is not None
        assert lead.country_code == "CN"

    countries = admin_client.get("/api/account-statistics/countries")
    assert countries.status_code == 200, countries.text
    cn = next(
        row
        for row in countries.json()["data"]["rows"]
        if row["countryCode"] == "CN"
    )
    assert cn["totalAccounts"] >= 1


def test_legacy_unverified_landing_pairing_can_request_a_fresh_code(
    admin_client: TestClient,
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    payload = {
        "phone": "+4915123456794",
        "deviceFingerprint": _device_fingerprint(),
    }

    first = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json=payload,
    )
    assert first.status_code == 200, first.text

    # Mock pairing deliberately leaves the same legacy shape that old
    # production releases persisted before a real connection was verified.
    assert admin_client.get(
        "/api/personal-accounts?keyword=4915123456794"
    ).json()["data"]["total"] == 0
    with SessionLocal() as db:
        stored = db.scalar(
            select(PersonalAccount).where(
                PersonalAccount.phone_e164 == "+4915123456794"
            )
        )
        assert stored is not None
        assert stored.status == "linked_offline"
        assert stored.validation_status == "validating"
        assert stored.admission_status == "reserved"
        assert stored.last_connected_at is None

    retried = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json=payload,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["pairing"]["pairingCode"] == "0000-0000"


def test_landing_reauthentication_preserves_account_ownership_and_enqueues_sync(
    admin_client: TestClient, monkeypatch
) -> None:
    public_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    initial = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456796",
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert initial.status_code == 200, initial.text
    initial_pairing = initial.json()["data"]["pairing"]
    verified = admin_client.get(
        initial_pairing["statusUrl"],
        headers={"Authorization": f"Bearer {initial_pairing['statusToken']}"},
    )
    assert verified.status_code == 200, verified.text
    account_id = int(initial_pairing["statusUrl"].split("/")[-2])
    process_pending_account_metadata_sync_jobs(limit=20)
    with SessionLocal() as db:
        initial_job = db.scalar(
            select(AccountMetadataSyncJob).where(
                AccountMetadataSyncJob.account_id == account_id
            )
        )
        assert initial_job is not None and initial_job.status == "succeeded"

    future_group = admin_client.post(
        "/api/account-groups", json={"name": "Only Future Reauth Accounts"}
    ).json()["data"]["group"]
    future_protocol = admin_client.post(
        "/api/protocol-nodes", json={"name": "Only Future Reauth Protocol"}
    ).json()["data"]["protocol"]
    assert admin_client.patch(
        f"/api/promotion/channels/{public_config['channel']['id']}",
        json={
            "accountGroupId": future_group["id"],
            "protocolNodeId": future_protocol["id"],
            "protocolPoolId": None,
        },
    ).status_code == 200

    with SessionLocal() as db:
        account = db.get(PersonalAccount, account_id)
        assert account is not None
        original = {
            "group": account.group_id,
            "protocol": account.protocol_id,
            "sourceType": account.source_ref_type,
            "sourceId": account.source_ref_id,
        }
        binding = db.scalar(
            select(AccountProxyBinding).where(
                AccountProxyBinding.account_public_id == account.gateway_account_id
            )
        )
        assert binding is not None
        original_proxy_id = binding.proxy_id
        account.status = "reauth_required"
        account.validation_status = "failed"
        db.commit()

    observed: list[str] = []
    original_reauthenticate = WaGatewayClient.reauthenticate

    def observe_reauthenticate(self, gateway_account_id, phone):
        observed.append(gateway_account_id)
        return original_reauthenticate(self, gateway_account_id, phone)

    monkeypatch.setattr(
        WaGatewayClient, "reauthenticate", observe_reauthenticate
    )
    current_config = admin_client.get(
        "/api/public/promotion/channels/de-facebook-demo"
    ).json()["data"]
    reauth = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456796",
            "deviceFingerprint": "2ef8bdbc97de077c45a46358ecc4ba42",
        },
    )
    assert reauth.status_code == 200, reauth.text
    pairing = reauth.json()["data"]["pairing"]
    assert len(observed) == 1
    assert int(pairing["statusUrl"].split("/")[-2]) == account_id
    with SessionLocal() as db:
        attempt = db.get(AccountPairingAttempt, int(pairing["attemptId"]))
        assert attempt is not None
        assert attempt.attempt_type == "reauthentication"
        assert attempt.account_group_id == original["group"]
        assert attempt.protocol_node_id == original["protocol"]

    reverified = admin_client.get(
        pairing["statusUrl"],
        headers={"Authorization": f"Bearer {pairing['statusToken']}"},
    )
    assert reverified.status_code == 200, reverified.text
    assert reverified.json()["data"]["pairingStatus"] == "verified"
    with SessionLocal() as db:
        account = db.get(PersonalAccount, account_id)
        assert account is not None
        assert account.admission_status == "active"
        assert account.group_id == original["group"]
        assert account.protocol_id == original["protocol"]
        assert account.source_ref_type == original["sourceType"]
        assert account.source_ref_id == original["sourceId"]
        binding = db.scalar(
            select(AccountProxyBinding).where(
                AccountProxyBinding.account_public_id == account.gateway_account_id
            )
        )
        assert binding is not None and binding.proxy_id == original_proxy_id
        jobs = list(
            db.scalars(
                select(AccountMetadataSyncJob).where(
                    AccountMetadataSyncJob.account_id == account.id
                )
            ).all()
        )
        assert [job.status for job in jobs].count("succeeded") == 1
        assert [job.status for job in jobs].count("pending") == 1


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
            "deviceFingerprint": _device_fingerprint(),
        },
    )
    assert started.status_code == 200, started.text
    pairing = started.json()["data"]["pairing"]
    assert pairing["statusTokenHeader"] == "Authorization"
    assert pairing["statusTokenScheme"] == "Bearer"
    query_token_status = admin_client.get(
        pairing["statusUrl"], params={"token": pairing["statusToken"]}
    )
    assert query_token_status.status_code == 403
    paused = admin_client.patch(
        f"/api/promotion/channels/{public_config['channel']['id']}",
        json={"status": "paused"},
    )
    assert paused.status_code == 200, paused.text

    cancelled = admin_client.post(
        pairing["cancelUrl"],
        headers={"Authorization": f"Bearer {pairing['statusToken']}"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"] == {
        "pairingStatus": "cancelled",
        "cancelled": True,
    }
    status = admin_client.get(
        pairing["statusUrl"],
        headers={"Authorization": f"Bearer {pairing['statusToken']}"},
    )
    assert status.status_code == 200, status.text
    assert status.json()["data"]["pairingStatus"] == "cancelled"
    assert status.json()["data"]["verified"] is False
    with SessionLocal() as db:
        projected = list(
            db.scalars(
                select(PromotionEvent).where(
                    PromotionEvent.idempotency_key
                    == f"pairing_failed:attempt:{pairing['attemptId']}"
                )
            ).all()
        )
        assert len(projected) == 1
        assert projected[0].metadata_json["detailCode"] == "pairing_cancelled"
        assert projected[0].metadata_json["stage"] == "pairing_cancel"
    assert admin_client.patch(
        f"/api/promotion/channels/{public_config['channel']['id']}",
        json={"status": "active"},
    ).status_code == 200


def test_pairing_gateway_failure_is_projected_once_to_monitoring(
    admin_client: TestClient,
) -> None:
    started = admin_client.post(
        "/api/public/promotion/channels/de-facebook-demo/pairing/start",
        json={
            "phone": "+4915123456805",
            "deviceFingerprint": "4ef8bdbc97de077c45a46358ecc4ba42",
        },
    )
    assert started.status_code == 200, started.text
    pairing = started.json()["data"]["pairing"]
    account_id = pairing["statusUrl"].split("/")[-2]

    interrupted = _gateway_account_event(
        admin_client,
        event_id="ast_landing_pairing_interrupted_test",
        account_id=account_id,
        from_state="pairing",
        to_state="unpaired",
        reason="pairing_connection_lost",
        occurred_at=utcnow(),
        provider_code="408",
        failure={
            "code": "pairing_confirmation_timeout",
            "title": "配对确认超时",
            "message": "手机未在配对会话有效期内完成绑定。",
            "suggestion": "请重新获取配对码，并及时在手机端完成确认。",
            "stage": "wait_pair_success",
            "retryable": True,
            "protocolCode": "408",
            "technicalMessage": "QR refs attempts ended",
        },
    )
    assert interrupted.status_code == 200, interrupted.text

    intake = admin_client.get(
        "/api/personal-accounts/intake/attempts?keyword=4915123456805"
    ).json()["data"]
    assert intake["total"] == 1
    assert intake["rows"][0]["status"] == "failed"
    assert intake["rows"][0]["terminalReason"] == "pairing_connection_lost"
    assert intake["rows"][0]["failureDetail"] == {
        "code": "pairing_confirmation_timeout",
        "title": "配对确认超时",
        "message": "手机未在配对会话有效期内完成绑定。",
        "suggestion": "请重新获取配对码，并及时在手机端完成确认。",
        "stage": "wait_pair_success",
        "retryable": True,
        "protocolCode": "408",
        "technicalMessage": "QR refs attempts ended",
    }

    with SessionLocal() as db:
        projected = list(
            db.scalars(
                select(PromotionEvent).where(
                    PromotionEvent.idempotency_key
                    == f"pairing_failed:attempt:{pairing['attemptId']}"
                )
            ).all()
        )
        assert len(projected) == 1
        assert projected[0].metadata_json["reasonCode"] == "gateway_failed"
        assert projected[0].metadata_json["detailCode"] == (
            "pairing_connection_lost"
        )
        assert projected[0].metadata_json["stage"] == "gateway_state"
        assert projected[0].metadata_json["failureDetail"]["code"] == (
            "pairing_confirmation_timeout"
        )


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
    with SessionLocal() as db:
        gateway_account_id = db.get(PersonalAccount, int(account_id)).gateway_account_id
    monkeypatch.setattr(
        WaGatewayClient,
        "list",
        lambda _self: [{"id": gateway_account_id, "phoneE164": "+12025551992", "state": "restricted"}],
    )
    synced = admin_client.get("/api/personal-accounts?sync=true&pageSize=100")
    assert synced.status_code == 200
    row = next(item for item in synced.json()["data"]["rows"] if item["id"] == account_id)
    assert row["status"] == "restricted"


def test_structured_payload_rejects_executable_html(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/materials",
        json={"name": "Unsafe", "type": "text", "contentJson": {"html": "<script>alert(1)</script>"}},
    )
    assert response.status_code == 422
