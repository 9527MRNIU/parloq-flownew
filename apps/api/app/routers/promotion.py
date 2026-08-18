from __future__ import annotations

import io
import base64
import hashlib
import hmac
import html as html_lib
import ipaddress
import json
import mimetypes
import re
import secrets
import stat
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business_schemas import (
    AdMetricImport,
    AdMetricInput,
    AdMetricUpdate,
    PromotionChannelCreate,
    PromotionChannelUpdate,
    PromotionEventInput,
    PromotionPairingStart,
    PromotionSuccessInput,
    PromotionTemplateIntegrationsUpdate,
    PromotionTemplateUpdate,
)
from app.config import get_settings
from app.deps import CurrentUser, DbSession, get_optional_current_user
from app.entity_ids import entity_id, identifier_filter, identifiers_filter
from app.snowflake import new_public_id, parse_snowflake_id

from app.models import (
    AdMetric,
    AccountGroup,
    AccountPairingAttempt,
    DomainRecord,
    MetaPixel,
    MetaConversionDelivery,
    PromotionAsset,
    PromotionChannel,
    PromotionEvent,
    PromotionLead,
    PromotionIntegration,
    PersonalAccount,
    PromotionTemplate,
    PromotionTemplateIntegration,
    PromotionTemplatePolicy,
    ProtocolNode,
    ProtocolPool,
    ProtocolPoolMember,
    UserAccount,
)
from app.security import utcnow
from app.serializers import iso
from app.services.promotion_integrations import (
    ActivePromotionIntegration,
    active_template_integrations,
    inject_runtime_integrations,
    integration_csp_sources,
)
from app.validation import parse_public_datetime, validate_structured_json


router = APIRouter(tags=["promotion"])
REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_ZIP = 20 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 500
PREVIEW_ASSET_TOKEN_TTL_SECONDS = 300
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".txt"}
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")
COUNTRY_DEFAULT_LOCALE = {
    "US":"en","GB":"en","CA":"en","AU":"en","NZ":"en","IE":"en","IN":"hi","PK":"ur","BD":"bn","LK":"si","NP":"ne",
    "CN":"zh-CN","TW":"zh-TW","HK":"zh-TW","MO":"zh-TW","JP":"ja","KR":"ko","VN":"vi","TH":"th","ID":"id","MY":"ms","SG":"en","PH":"en",
    "DE":"de","AT":"de","CH":"de","FR":"fr","BE":"fr","NL":"nl","LU":"fr","ES":"es","MX":"es","AR":"es","CO":"es","CL":"es","PE":"es","VE":"es","EC":"es","UY":"es","PY":"es","BO":"es",
    "PT":"pt","BR":"pt-BR","IT":"it","PL":"pl","CZ":"cs","SK":"sk","HU":"hu","RO":"ro","BG":"bg","GR":"el","SE":"sv","NO":"no","DK":"da","FI":"fi","IS":"is",
    "RU":"ru","UA":"uk","BY":"ru","TR":"tr","IL":"he","SA":"ar","AE":"ar","QA":"ar","KW":"ar","BH":"ar","OM":"ar","JO":"ar","LB":"ar","IQ":"ar","EG":"ar","MA":"ar","DZ":"ar","TN":"ar",
    "ZA":"en","NG":"en","KE":"en","GH":"en","TZ":"sw","ET":"am","UG":"en","SN":"fr","CI":"fr","CM":"fr","AO":"pt","MZ":"pt",
}
RTL_LANGUAGE_BASES = {"ar", "fa", "he", "ps", "ur"}
MAX_LOCALE_ASSET_BYTES = 256 * 1024
MAX_LOCALIZED_COPY_ITEMS = 256
ACTIVE_PAIRING_STATUSES = {"code_issued", "waiting_phone", "reconnecting"}
TERMINAL_PAIRING_STATUSES = {"verified", "expired", "cancelled", "failed"}
MAX_LOCALIZED_COPY_VALUE = 8_000
PUBLIC_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "public"


TRACKER_JS = r'''(()=>{const node=document.getElementById("promotion-runtime-config");if(!node)return;let c={};try{c=JSON.parse(node.textContent||"{}")}catch{return}const started=Date.now(),id=()=>crypto.randomUUID(),policy=c.templatePolicy||{},meta=c.meta||{},mapping=meta.eventMapping||{};let visitor;try{visitor=localStorage.getItem("promotion_visitor_id")||id();localStorage.setItem("promotion_visitor_id",visitor)}catch{visitor=id()}const seenMeta=eventId=>{const key=`promotion_meta_event:${eventId}`;try{if(sessionStorage.getItem(key))return true;sessionStorage.setItem(key,"1")}catch{}return false},fireMeta=(eventKey,eventId)=>{const name=mapping[eventKey];if(!window.fbq||!name||!eventId||seenMeta(eventId))return;window.fbq("track",name,{}, {eventID:eventId})};if(meta.browserEnabled&&meta.datasetId&&/^[A-Za-z0-9_.:-]{1,120}$/.test(meta.datasetId)){const f=window.fbq=function(){f.callMethod?f.callMethod.apply(f,arguments):f.queue.push(arguments)};if(!window._fbq)window._fbq=f;f.push=f;f.loaded=true;f.version="2.0";f.queue=[];const s=document.createElement("script");s.async=true;s.src="https://connect.facebook.net/en_US/fbevents.js";document.head.appendChild(s);f("init",meta.datasetId)}const body=(eventType,eventId,extra={})=>JSON.stringify({eventType,idempotencyKey:eventId,visitorId:visitor,sessionToken:c.sessionToken,...extra}),send=(eventType,extra={},eventId=id())=>fetch(c.eventUrl,{method:"POST",headers:{"Content-Type":"text/plain;charset=UTF-8"},body:body(eventType,eventId,extra),keepalive:true}),signals=()=>{if(policy.deviceSignals==="off")return{};const base={language:navigator.language,timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone,viewport:[innerWidth,innerHeight],screen:[screen.width,screen.height],pixelRatio:devicePixelRatio,touchPoints:navigator.maxTouchPoints||0};if(policy.deviceSignals==="enhanced")Object.assign(base,{platform:navigator.platform||"",hardwareConcurrency:navigator.hardwareConcurrency||null,deviceMemory:navigator.deviceMemory||null,colorDepth:screen.colorDepth||null,userAgent:navigator.userAgent});return base},readMetaEvent=async response=>{try{const value=await response.clone().json(),event=value?.data?.metaEvent;if(event?.name&&event?.eventId&&!seenMeta(event.eventId)&&window.fbq)window.fbq("track",event.name,{}, {eventID:event.eventId})}catch{}return response},fail=async(response,fallback)=>{let value={};try{value=await response.clone().json()}catch{}const info=value?.error||{},message=info.message||value?.detail||fallback,error=new Error(message);error.name="AccountLinkError";error.code=info.code||fallback;error.retryable=Boolean(info.retryable);error.status=response.status;throw error},pairingHeaders=pairing=>({Authorization:`Bearer ${pairing.statusToken}`});const bridge=window.PromotionBridge=window.PromotionBridge||{};bridge.version="promotion-browser-bridge/v2";bridge.submitPhone=async(phone,metadata={})=>{if(window.__promotionInspectionBlocked)throw new Error("inspection_blocked");const eventId=id();fireMeta("phone_submit",eventId);const tracked=await send("phone_submit",{phone,metadata},eventId);if(!tracked.ok)return fail(tracked,"phone_submit_failed");const paired=await fetch(c.pairingStartUrl,{method:"POST",headers:{"Content-Type":"text/plain;charset=UTF-8"},body:JSON.stringify({phone,visitorId:visitor,sessionToken:c.sessionToken})});if(!paired.ok)return fail(paired,"pairing_start_failed");return readMetaEvent(paired)};bridge.getPairingStatus=async pairing=>readMetaEvent(await fetch(pairing.statusUrl,{method:"GET",headers:pairingHeaders(pairing),cache:"no-store"}));bridge.cancelPairing=pairing=>fetch(pairing.cancelUrl,{method:"POST",headers:pairingHeaders(pairing)});const pageEventId=id();fireMeta("page_view",pageEventId);send("page_view",{metadata:{deviceSignals:signals()}},pageEventId).catch(()=>{});if(c.inAppBrowserMode==="guide_external"&&/(FBAN|FBAV|Instagram)/i.test(navigator.userAgent))dispatchEvent(new CustomEvent("promotion:in-app-browser",{detail:{mode:"guide_external"}}));addEventListener("promotion:inspection-detected",e=>send("inspection_detected",{metadata:e.detail||{}}).catch(()=>{}));document.addEventListener("submit",e=>{if(e.target.matches("form[data-promotion-manual]"))return;const p=e.target.querySelector('input[type="tel"],input[name*="phone" i]');if(p&&p.value)bridge.submitPhone(p.value).catch(()=>{})});addEventListener("pagehide",()=>{const eventId=id();navigator.sendBeacon(c.eventUrl,new Blob([body("visit_end",eventId,{metadata:{durationMs:Math.max(0,Date.now()-started)}})],{type:"text/plain;charset=UTF-8"}))})})();'''


# Conversion-page display rules and interaction hardening are platform-owned so
# imported templates behave consistently. Phone inputs never render a leading
# plus, while protocol normalization remains a server-side concern.
LANDING_GUARD_JS = r'''(()=>{const phoneSelector='input[type="tel"],input[name*="phone" i]',cleanPhone=input=>{if(!input?.matches?.(phoneSelector))return;input.value=String(input.value||"").replace(/\+/g,"")},preparePhones=()=>document.querySelectorAll(phoneSelector).forEach(input=>{cleanPhone(input);const parent=input.parentElement;if(parent)Array.from(parent.children).forEach(child=>{if(child!==input&&String(child.textContent||"").trim()==="+")child.hidden=true})});document.readyState==="loading"?addEventListener("DOMContentLoaded",preparePhones,{once:true}):preparePhones();addEventListener("input",event=>cleanPhone(event.target),true);const node=document.getElementById("promotion-runtime-config");let config={};try{config=JSON.parse(node?.textContent||"{}")}catch{}const policy=config.templatePolicy||{},mode=policy.protectionMode||"strict",preview=Boolean(config.previewMode),stop=e=>{e.preventDefault();e.stopImmediatePropagation()};addEventListener("contextmenu",e=>{if(e.pointerType!=="touch")stop(e)},true);addEventListener("keydown",e=>{const k=String(e.key||"").toLowerCase(),primary=e.ctrlKey||e.metaKey,inspect=e.key==="F12"||(primary&&e.shiftKey&&["i","j","c"].includes(k))||(primary&&["u","s"].includes(k));if(inspect)stop(e)},true);if(mode==="basic"||preview)return;let handled=false;const detected=reason=>{if(handled)return;handled=true;dispatchEvent(new CustomEvent("promotion:inspection-detected",{detail:{reason,mode}}));const action=policy.devtoolsAction||"blank";if(action==="block")window.__promotionInspectionBlocked=true;if(action==="blank"){document.documentElement.innerHTML="";document.title=""}};const inspect=()=>{if(Math.abs(outerWidth-innerWidth)>180||Math.abs(outerHeight-innerHeight)>180)return detected("window-gap");if(window.eruda||window.vConsole||document.querySelector(".eruda-container,#__vconsole"))return detected("mobile-console");let consoleProbe=false;const probe=new Image;Object.defineProperty(probe,"id",{get(){consoleProbe=true;return""}});console.debug(probe);if(consoleProbe)return detected("console-probe");if(mode==="strict"){const before=performance.now();debugger;if(performance.now()-before>220)return detected("debugger-delay")}};setInterval(inspect,mode==="strict"?900:1600);inspect()})();'''

DEFAULT_TEMPLATE_POLICY = {
    "protectionMode": "strict",
    "devtoolsAction": "blank",
    "lockViewportZoom": True,
    "deviceSignals": "enhanced",
    "updatedAt": None,
}


def _session_token(
    channel: PromotionChannel, traffic_source: str = "direct"
) -> str:
    if traffic_source not in {"direct", "fission"}:
        raise ValueError("unsupported promotion traffic source")
    issued_at = int(utcnow().timestamp())
    payload = {
        "channel": entity_id(channel),
        "trafficSource": traffic_source,
        "iat": issued_at,
        "exp": issued_at + 1800,
        "nonce": secrets.token_hex(8),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _verify_session_token(channel: PromotionChannel, token: str) -> dict:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (
            payload.get("channel") != entity_id(channel)
            or payload.get("trafficSource", "direct") not in {"direct", "fission"}
            or int(payload.get("exp", 0)) < int(utcnow().timestamp())
            or not payload.get("iat")
        ):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=403, detail="推广会话已失效") from None
    return payload


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _pairing_status_token(
    channel: PromotionChannel,
    account: PersonalAccount,
    attempt: AccountPairingAttempt,
    visitor_id: str,
) -> str:
    issued_at = int(utcnow().timestamp())
    expires_at = int(_utc_datetime(attempt.expires_at).timestamp())
    payload = {
        "channel": entity_id(channel),
        "account": str(account.id),
        "attempt": entity_id(attempt),
        "visitor": visitor_id,
        "iat": issued_at,
        "pairExp": expires_at,
        "exp": max(issued_at + 600, expires_at + 420),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _verify_pairing_status_token(
    channel: PromotionChannel,
    account: PersonalAccount,
    attempt: AccountPairingAttempt,
    token: str,
) -> dict:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(
            get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        if (
            payload.get("channel") != entity_id(channel)
            or payload.get("account") != str(account.id)
            or payload.get("attempt") != entity_id(attempt)
            or int(payload.get("exp", 0)) < int(utcnow().timestamp())
        ):
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=403, detail="账号链接状态凭证已失效") from None


def _pairing_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=403, detail="缺少账号链接状态凭证")
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise HTTPException(status_code=403, detail="账号链接状态凭证格式不正确")
    return parts[1]


def _public_pairing_status(
    *,
    state: str,
    gateway_pairing_status: str,
    verified: bool,
    attempt_status: str,
    expires_at: datetime,
) -> str:
    if attempt_status in TERMINAL_PAIRING_STATUSES:
        return attempt_status
    if verified:
        return "verified"
    if _utc_datetime(expires_at) <= utcnow():
        return "expired"
    if gateway_pairing_status in {"waiting_phone", "reconnecting"}:
        return gateway_pairing_status
    if gateway_pairing_status in {"expired", "cancelled", "failed"}:
        return gateway_pairing_status
    if state in {"unpaired", "reauth_required", "restricted"}:
        return "failed"
    return "waiting_phone"


def _public_pairing_error(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    """Return one stable, white-label error contract for the public bridge."""

    error = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    headers = {"Access-Control-Allow-Origin": "null"}
    if retry_after_seconds is not None:
        error["retryAfterSeconds"] = max(int(retry_after_seconds), 1)
        headers["Retry-After"] = str(error["retryAfterSeconds"])
        headers["Access-Control-Expose-Headers"] = "Retry-After"
    return JSONResponse(
        {"error": error},
        status_code=status_code,
        headers=headers,
    )


def _pairing_rate_limit_response(decision) -> JSONResponse | None:
    if decision.allowed:
        return None
    return _public_pairing_error(
        429,
        "rate_limited",
        "绑定请求过于频繁，请稍后再试",
        retryable=True,
        retry_after_seconds=decision.retry_after_seconds,
    )


def _pairing_rate_limit_unavailable_response() -> JSONResponse:
    return _public_pairing_error(
        503,
        "service_temporarily_unavailable",
        "绑定服务暂时不可用，请稍后再试",
        retryable=True,
        retry_after_seconds=5,
    )


def _template(db: DbSession, identifier: str, user) -> PromotionTemplate:
    statement = select(PromotionTemplate).where(identifier_filter(PromotionTemplate, identifier), PromotionTemplate.archived_at.is_(None))
    if user.role != "admin": statement = statement.where(PromotionTemplate.created_by == user.id)
    item = db.scalar(statement)
    if item is None: raise HTTPException(status_code=404, detail="推广模板不存在")
    return item


def _channel(db: DbSession, identifier: str, user) -> PromotionChannel:
    statement = select(PromotionChannel).where(identifier_filter(PromotionChannel, identifier), PromotionChannel.archived_at.is_(None))
    if user.role != "admin": statement = statement.where(PromotionChannel.created_by == user.id)
    item = db.scalar(statement)
    if item is None: raise HTTPException(status_code=404, detail="推广渠道不存在")
    return item


def _template_integration_ids(db: DbSession, template_id: int) -> list[str]:
    ids = db.scalars(
        select(PromotionTemplateIntegration.integration_id)
        .where(
            PromotionTemplateIntegration.template_id == template_id,
            PromotionTemplateIntegration.enabled.is_(True),
        )
        .order_by(PromotionTemplateIntegration.integration_id)
    ).all()
    return [str(value) for value in ids]


def template_row(db: DbSession, item: PromotionTemplate) -> dict:
    manifest = item.manifest_json or {}
    return {"id": entity_id(item), "name": item.name, "description": item.description, "version": item.version, "status": item.status, "manifest": manifest, "defaultLocale": manifest.get("defaultLocale"), "supportedLocales": manifest.get("supportedLocales", []), "i18n": manifest.get("i18n"), "assetCount": item.asset_count, "totalSize": item.total_size, "integrationIds": _template_integration_ids(db, item.id), "createdAt": iso(item.created_at), "updatedAt": iso(item.updated_at)}


def _channel_hostname(item: PromotionChannel, domain: DomainRecord | None) -> str:
    if domain is None:
        return ""
    prefix = (item.subdomain_prefix or "").strip().lower()
    return f"{prefix}.{domain.hostname}" if prefix else domain.hostname


def channel_row(db: DbSession, item: PromotionChannel) -> dict:
    template = db.get(PromotionTemplate, item.template_id); domain = db.get(DomainRecord, item.domain_id) if item.domain_id else None; pixel = db.get(MetaPixel, item.pixel_id) if item.pixel_id else None; account_group = db.get(AccountGroup, item.account_group_id) if item.account_group_id else None; protocol_node = db.get(ProtocolNode, item.protocol_node_id) if item.protocol_node_id else None; protocol_pool = db.get(ProtocolPool, item.protocol_pool_id) if item.protocol_pool_id else None
    hostname = _channel_hostname(item, domain)
    from app.services.meta_conversions import normalized_meta_event_mapping
    from app.services.protocol_nodes import protocol_health

    manifest = template.manifest_json if template else {}
    if protocol_node is not None:
        route_health, route_reason = protocol_health(db, protocol_node)
        route_mode = "node"
    elif protocol_pool is not None:
        members = list(
            db.scalars(
                select(ProtocolNode)
                .join(
                    ProtocolPoolMember,
                    ProtocolPoolMember.protocol_node_id == ProtocolNode.id,
                )
                .where(
                    ProtocolPoolMember.pool_id == protocol_pool.id,
                    ProtocolPoolMember.enabled.is_(True),
                )
                .order_by(ProtocolPoolMember.priority, ProtocolPoolMember.id)
            ).all()
        )
        states = [protocol_health(db, member) for member in members]
        route_health = "available" if any(state[0] == "available" for state in states) else "offline"
        route_reason = None if route_health == "available" else "协议池中没有可接入节点"
        route_mode = "pool"
    else:
        route_health, route_reason, route_mode = "offline", "尚未配置协议路由", "none"
    return {
        "id": entity_id(item),
        "type": item.channel_type,
        "name": item.name,
        "countryCode": item.country_code,
        "templateId": entity_id(template) if template else None,
        "templateName": template.name if template else None,
        "domainId": entity_id(domain) if domain else None,
        "baseHostname": domain.hostname if domain else None,
        "subdomainPrefix": item.subdomain_prefix or None,
        "hostname": hostname or None,
        "slug": item.slug,
        "pixelId": entity_id(pixel) if pixel else None,
        "pixelName": pixel.name if pixel else None,
        "datasetId": pixel.dataset_id if pixel else None,
        "accountGroupId": entity_id(account_group) if account_group else None,
        "accountGroupName": account_group.name if account_group else None,
        "protocolNodeId": entity_id(protocol_node) if protocol_node else None,
        "protocolNodeName": protocol_node.name if protocol_node else None,
        "protocolPoolId": entity_id(protocol_pool) if protocol_pool else None,
        "protocolPoolName": protocol_pool.name if protocol_pool else None,
        "routeVersion": item.route_version,
        "metaBrowserPixelEnabled": item.meta_browser_pixel_enabled,
        "metaCapiEnabled": item.meta_capi_enabled,
        "metaEventMapping": normalized_meta_event_mapping(item.meta_event_mapping_json),
        "inAppBrowserMode": item.in_app_browser_mode,
        "newAccountMarketingEnabled": item.new_account_marketing_enabled,
        "effectiveConfig": {
            "template": {
                "schema": manifest.get("schema"),
                "runtime": manifest.get("runtime"),
                "capabilities": manifest.get("capabilities", []),
                "pairingContract": (manifest.get("requirements") or {}).get("pairingContract", "promotion-public-pairing/v1"),
                "componentKit": (manifest.get("requirements") or {}).get("componentKit"),
            },
            "route": {
                "mode": route_mode,
                "version": item.route_version,
                "health": route_health,
                "reason": route_reason,
                "fallback": route_mode == "pool",
            },
            "accountGroupReady": account_group is not None,
            "meta": {
                "pixelReady": bool(pixel and pixel.enabled and pixel.archived_at is None),
                "browserEnabled": bool(item.meta_browser_pixel_enabled and pixel),
                "capiEnabled": bool(item.meta_capi_enabled and pixel and pixel.capi_token_ciphertext),
            },
        },
        "localeMode": item.locale_mode,
        "locale": item.locale,
        "status": item.status,
        "launchAt": iso(item.launch_at),
        "publicUrl": f"https://{hostname}/{item.slug}" if hostname else f"/api/public/promotion/channels/{item.slug}/render",
        "fissionPublicUrl": f"https://{hostname}/{item.slug}/1" if hostname else f"/api/public/promotion/channels/{item.slug}/fission/render",
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _manifest_protocol(manifest: dict) -> dict:
    schema = str(manifest.get("schema") or "promotion-template/v1")
    if schema not in {
        "promotion-template/v1",
        "promotion-template/v2",
        "parloq-promotion-template/v1",
    }:
        raise HTTPException(status_code=422, detail="manifest schema 仅支持 promotion-template/v1 或 v2")
    normalized_schema = (
        "promotion-template/v2" if schema == "promotion-template/v2" else "promotion-template/v1"
    )
    entry = str(manifest.get("entry") or "index.html")
    if entry != "index.html":
        raise HTTPException(status_code=422, detail="manifest entry 必须是 index.html")
    bundle_format = str(manifest.get("format") or "static-bundle")
    if bundle_format not in {"static-bundle", "vite-dist"}:
        raise HTTPException(status_code=422, detail="manifest format 仅支持 static-bundle/vite-dist")
    raw_capabilities = manifest.get("capabilities") or ["phone-pairing"]
    if not isinstance(raw_capabilities, list) or any(
        value != "phone-pairing" for value in raw_capabilities
    ):
        raise HTTPException(status_code=422, detail="manifest capabilities 目前仅支持 phone-pairing")
    capabilities = list(dict.fromkeys(raw_capabilities))
    if "phone-pairing" not in capabilities:
        raise HTTPException(status_code=422, detail="模板必须声明 phone-pairing 能力")
    default = str(manifest.get("defaultLocale") or "en").replace("_", "-")
    if not LOCALE_RE.fullmatch(default): raise HTTPException(status_code=422, detail="manifest defaultLocale 格式不正确")
    raw_supported = manifest.get("supportedLocales") or [default]
    if not isinstance(raw_supported, list) or len(raw_supported) > 128: raise HTTPException(status_code=422, detail="manifest supportedLocales 格式不正确")
    supported = []
    for raw in raw_supported:
        locale = str(raw).replace("_", "-")
        if not LOCALE_RE.fullmatch(locale): raise HTTPException(status_code=422, detail="manifest supportedLocales 包含无效 locale")
        if locale not in supported: supported.append(locale)
    if default not in supported: supported.insert(0, default)
    raw_i18n = manifest.get("i18n") if isinstance(manifest.get("i18n"), dict) else {}
    mode = str(raw_i18n.get("mode") or "bundled")
    if mode not in {"bundled", "runtime"}: raise HTTPException(status_code=422, detail="manifest i18n.mode 仅支持 bundled/runtime")
    path = str(raw_i18n.get("path") or "locales/{locale}.json")
    if ".." in PurePosixPath(path).parts or path.startswith("/"): raise HTTPException(status_code=422, detail="manifest i18n.path 不安全")
    fallback = str(raw_i18n.get("fallbackLocale") or default).replace("_", "-")
    if fallback not in supported: fallback = default
    runtime = str(
        manifest.get("runtime")
        or (
            "promotion-browser-bridge/v2"
            if normalized_schema == "promotion-template/v2"
            else "promotion-browser-bridge/v1"
        )
    )
    expected_runtime = (
        "promotion-browser-bridge/v2"
        if normalized_schema == "promotion-template/v2"
        else "promotion-browser-bridge/v1"
    )
    if runtime != expected_runtime:
        raise HTTPException(
            status_code=422,
            detail=f"{normalized_schema} 必须使用 {expected_runtime}",
        )
    requirements = manifest.get("requirements") or {}
    if not isinstance(requirements, dict):
        raise HTTPException(status_code=422, detail="manifest requirements 格式不正确")
    pairing_contract = str(
        requirements.get("pairingContract") or "promotion-public-pairing/v1"
    )
    if pairing_contract != "promotion-public-pairing/v1":
        raise HTTPException(status_code=422, detail="模板请求了不支持的账号接入契约")
    component_kit = requirements.get("componentKit")
    if component_kit not in {None, "account-link-elements/v1"}:
        raise HTTPException(status_code=422, detail="模板请求了不支持的白标组件库")
    return {
        **manifest,
        "schema": normalized_schema,
        "entry": entry,
        "format": bundle_format,
        "capabilities": capabilities,
        "runtime": expected_runtime,
        "requirements": {
            **requirements,
            "pairingContract": pairing_contract,
            **({"componentKit": component_kit} if component_kit else {}),
        },
        "interactionProtection": "platform",
        "defaultLocale": default,
        "supportedLocales": supported,
        "i18n": {
            **raw_i18n,
            "mode": mode,
            "path": path,
            "fallbackLocale": fallback,
        },
    }


def _safe_bundle(raw: bytes) -> tuple[dict, str, list[tuple[str, str, bytes]], int]:
    if len(raw) > MAX_ZIP: raise HTTPException(status_code=413, detail="ZIP 文件超过 20MB")
    try: archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile: raise HTTPException(status_code=422, detail="模板包不是有效 ZIP") from None
    files = [info for info in archive.infolist() if not info.is_dir()]
    if len(files) > MAX_FILES: raise HTTPException(status_code=422, detail="模板包文件数量超过限制")
    total = 0; values: dict[str, bytes] = {}
    for info in files:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise HTTPException(status_code=422, detail="模板包包含不安全路径")
        if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise HTTPException(status_code=422, detail="模板包不能包含符号链接")
        normalized = path.as_posix()
        if PurePosixPath(normalized).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=422, detail=f"模板文件类型不允许：{normalized}")
        if info.file_size > MAX_FILE: raise HTTPException(status_code=422, detail=f"单文件超过 5MB：{normalized}")
        total += info.file_size
        if total > MAX_TOTAL: raise HTTPException(status_code=422, detail="模板解压总大小超过 50MB")
        values[normalized] = archive.read(info)
    index_candidates = [path for path in values if path == "index.html" or path.endswith("/index.html")]
    if len(index_candidates) != 1:
        raise HTTPException(status_code=422, detail="模板包必须包含唯一的 index.html")
    root = PurePosixPath(index_candidates[0]).parent.as_posix()
    prefix = "" if root == "." else root + "/"
    normalized_values = {path[len(prefix):]: content for path, content in values.items() if path.startswith(prefix)}
    values = normalized_values
    try:
        manifest = json.loads(values["manifest.json"].decode("utf-8")) if "manifest.json" in values else {"version": "1", "entry": "index.html", "format": "vite-dist", "defaultLocale": "en", "supportedLocales": ["en"], "i18n": {"mode": "bundled", "path": "locales/{locale}.json", "fallbackLocale": "en"}}
        index_html = values["index.html"].decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError): raise HTTPException(status_code=422, detail="manifest.json 或 index.html 编码无效") from None
    manifest = _manifest_protocol(validate_structured_json(manifest))
    assets = [(path, mimetypes.guess_type(path)[0] or "application/octet-stream", content) for path, content in values.items() if path not in {"manifest.json", "index.html"}]
    return manifest, index_html, assets, total


def _replace_bundle(db: DbSession, item: PromotionTemplate, raw: bytes) -> None:
    manifest, html, assets, total = _safe_bundle(raw)
    for old in db.scalars(select(PromotionAsset).where(PromotionAsset.template_id == item.id)).all(): db.delete(old)
    # Asset paths are unique per template. Flush the deletes before adding a
    # new version that commonly reuses paths such as assets/app.js.
    db.flush()
    item.manifest_json = manifest; item.index_html = html; item.version = str(manifest.get("version") or str(int(item.version) + 1 if item.version.isdigit() else uuid4().hex[:8]))[:40]; item.asset_count = len(assets); item.total_size = total
    for path, content_type, content in assets: db.add(PromotionAsset(template_id=item.id, path=path, content_type=content_type, size=len(content), content=content))


def _form_integration_ids(value: str | None) -> list[str] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        payload = PromotionTemplateIntegrationsUpdate(integrationIds=parsed)
    except (json.JSONDecodeError, ValidationError, TypeError):
        raise HTTPException(status_code=422, detail="模板集成配置格式不正确") from None
    return payload.integration_ids


def _set_template_integrations(
    db: DbSession,
    item: PromotionTemplate,
    integration_ids: list[str],
    user,
) -> None:
    integration_pks = [parse_snowflake_id(value) for value in integration_ids]
    integrations: list[PromotionIntegration] = []
    if integration_pks:
        statement = select(PromotionIntegration).where(
            PromotionIntegration.id.in_(integration_pks),
            PromotionIntegration.archived_at.is_(None),
        )
        if user.role != "admin":
            statement = statement.where(PromotionIntegration.created_by == user.id)
        integrations = list(db.scalars(statement).all())
        if {value.id for value in integrations} != set(integration_pks):
            raise HTTPException(status_code=404, detail="包含不可用的集成")
    selected = {value.id for value in integrations}
    existing = {
        value.integration_id: value
        for value in db.scalars(
            select(PromotionTemplateIntegration).where(
                PromotionTemplateIntegration.template_id == item.id
            )
        ).all()
    }
    for integration_id, binding in existing.items():
        binding.enabled = integration_id in selected
    for integration_id in selected.difference(existing):
        db.add(
            PromotionTemplateIntegration(
                template_id=item.id,
                integration_id=integration_id,
                enabled=True,
            )
        )


def _inject_after_head_open(html: str, markup: str) -> str:
    """Place base markup before the browser discovers any relative resource."""
    pattern = re.compile(r"<head\b[^>]*>", re.I)
    match = pattern.search(html)
    if match is None:
        return markup + html
    return html[: match.end()] + markup + html[match.end() :]


def _request_origin(request: Request) -> str:
    """Return one CSP-safe HTTP origin, preserving the public proxy host."""
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    host = forwarded_host or request.headers.get("host", "").strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    scheme = forwarded_proto or request.url.scheme
    if scheme not in {"http", "https"} or not re.fullmatch(
        r"[A-Za-z0-9.\-:\[\]]{1,255}", host
    ):
        raise HTTPException(status_code=400, detail="请求来源无效")
    return f"{scheme}://{host}"


def _sandbox_csp(
    request: Request,
    *,
    preview: bool = False,
    integrations: list[ActivePromotionIntegration] | None = None,
) -> str:
    origin = _request_origin(request)
    active_integrations = integrations or []
    sandbox = "sandbox allow-scripts allow-forms"
    if not preview and active_integrations:
        sandbox += " allow-same-origin"
    sandbox += " allow-top-navigation-by-user-activation"
    script_origins, frame_origins, connect_origins = integration_csp_sources(
        active_integrations
    )
    external_scripts = "".join(f" {value}" for value in sorted(script_origins))
    external_connections = "".join(
        f" {value}" for value in sorted(connect_origins)
    )
    frames = " ".join(sorted(frame_origins)) or "'none'"
    if preview:
        return (
            f"{sandbox}; default-src 'none'; base-uri {origin}; "
            f"script-src 'unsafe-inline' {origin}{external_scripts}; "
            f"style-src 'unsafe-inline' {origin} data:; "
            f"img-src {origin} data: blob:; font-src {origin} data:; "
            f"media-src {origin} data: blob:; connect-src {origin}{external_connections}; "
            f"worker-src blob:; object-src 'none'; frame-src {frames}; "
            f"form-action 'none'; frame-ancestors {origin}"
        )
    return (
        f"{sandbox}; default-src 'none'; base-uri {origin}; "
        f"script-src {origin} https://connect.facebook.net{external_scripts}; "
        f"connect-src {origin} https://connect.facebook.net https://www.facebook.com{external_connections}; "
        f"img-src {origin} data: blob: https://www.facebook.com; "
        f"style-src 'unsafe-inline' {origin}; font-src {origin} data:; "
        f"media-src 'none'; object-src 'none'; frame-src {frames}; "
        f"form-action {origin}; frame-ancestors 'none'"
    )


def _apply_viewport_policy(html: str, template_policy: dict) -> str:
    """Lock zoom only when the tenant explicitly opts into conversion mode."""
    if not template_policy.get("lockViewportZoom"):
        return html
    viewport = (
        '<meta name="viewport" '
        'content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">'
    )
    pattern = re.compile(r'<meta\b[^>]*\bname\s*=\s*(["\'])viewport\1[^>]*>', re.I)
    if pattern.search(html):
        return pattern.sub(viewport, html, count=1)
    return _inject_after_head_open(html, viewport)


def _runtime_template_policy(db: DbSession, owner_id: int) -> dict:
    """Read a policy without mutating a public GET when defaults are enough."""
    item = db.scalar(
        select(PromotionTemplatePolicy).where(
            PromotionTemplatePolicy.created_by == owner_id
        )
    )
    if item is None:
        return dict(DEFAULT_TEMPLATE_POLICY)
    from app.routers.promotion_policy import template_policy_row

    return template_policy_row(item)


def _preview_asset_token(item: PromotionTemplate) -> str:
    """Create a short-lived capability for sandboxed preview resources."""
    payload = {
        "template": entity_id(item),
        "exp": int(utcnow().timestamp()) + PREVIEW_ASSET_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_hex(8),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        get_settings().app_secret_key.encode(),
        f"promotion-preview-assets:{encoded}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _verify_preview_asset_token(template_id: str, token: str) -> None:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(
            get_settings().app_secret_key.encode(),
            f"promotion-preview-assets:{encoded}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        if (
            payload.get("template") != template_id
            or int(payload.get("exp", 0)) < int(utcnow().timestamp())
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        # A preview capability is intentionally indistinguishable from a
        # missing asset when it is invalid or expired.
        raise HTTPException(status_code=404) from None


def _preview_asset_response(
    db: DbSession,
    item: PromotionTemplate,
    asset_path: str,
    asset_root: str,
) -> Response:
    normalized = PurePosixPath(asset_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(status_code=404)
    asset = db.scalar(
        select(PromotionAsset).where(
            PromotionAsset.template_id == item.id,
            PromotionAsset.path == normalized.as_posix(),
        )
    )
    if asset is None:
        raise HTTPException(status_code=404)
    content = asset.content
    if asset.content_type in {"text/css", "application/javascript", "text/javascript"}:
        content = re.sub(
            rb'(["\'(])/assets/',
            rb"\1" + f"{asset_root}assets/".encode(),
            content,
        )
    return Response(
        content,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/api/promotion/template-kits/account-link-elements-v1.zip")
def download_account_link_starter(_current_user: CurrentUser) -> Response:
    root = Path(__file__).resolve().parents[1] / "template_kits" / "account_link_v1"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(root).as_posix())
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="account-link-capability-theme-v1.zip"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/promotion/templates")
def list_templates(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PromotionTemplate).where(PromotionTemplate.archived_at.is_(None))
    if current_user.role != "admin": statement = statement.where(PromotionTemplate.created_by == current_user.id)
    items = db.scalars(statement.order_by(PromotionTemplate.created_at.desc())).all(); return {"data": {"rows": [template_row(db, x) for x in items], "total": len(items)}}


@router.post("/api/promotion/templates", status_code=status.HTTP_201_CREATED)
def import_template(db: DbSession, current_user: CurrentUser, file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=120), description: str | None = Form(default=None, max_length=2000), integration_ids: str | None = Form(default=None, alias="integrationIds")) -> dict:
    if not file.filename or not file.filename.lower().endswith(".zip"): raise HTTPException(status_code=422, detail="请选择 ZIP 模板包")
    manifest, html, assets, total = _safe_bundle(file.file.read(MAX_ZIP + 1))
    item = PromotionTemplate(public_id=new_public_id("ptpl"), name=name, description=description, version=str(manifest.get("version") or "1")[:40], status="active", manifest_json=manifest, index_html=html, asset_count=len(assets), total_size=total, created_by=current_user.id)
    db.add(item); db.flush()
    for path, content_type, content in assets: db.add(PromotionAsset(template_id=item.id, path=path, content_type=content_type, size=len(content), content=content))
    selected_integrations = _form_integration_ids(integration_ids)
    if selected_integrations is not None: _set_template_integrations(db, item, selected_integrations, current_user)
    db.commit(); db.refresh(item); return {"data": {"template": template_row(db, item)}}


@router.post("/api/promotion/templates/{template_id}/versions")
def replace_template_version(template_id: str, db: DbSession, current_user: CurrentUser, file: UploadFile = File(...), integration_ids: str | None = Form(default=None, alias="integrationIds")) -> dict:
    item = _template(db, template_id, current_user)
    if not file.filename or not file.filename.lower().endswith(".zip"): raise HTTPException(status_code=422, detail="请选择 ZIP 模板包")
    _replace_bundle(db, item, file.file.read(MAX_ZIP + 1))
    selected_integrations = _form_integration_ids(integration_ids)
    if selected_integrations is not None: _set_template_integrations(db, item, selected_integrations, current_user)
    db.commit(); db.refresh(item); return {"data": {"template": template_row(db, item)}}


@router.get("/api/promotion/templates/{template_id}")
def get_template(template_id: str, db: DbSession, current_user: CurrentUser) -> dict: return {"data": {"template": template_row(db, _template(db, template_id, current_user))}}


@router.patch("/api/promotion/templates/{template_id}")
def update_template(template_id: str, payload: PromotionTemplateUpdate, db: DbSession, current_user: CurrentUser) -> dict:
    item = _template(db, template_id, current_user)
    if payload.name is not None: item.name = payload.name
    if "description" in payload.model_fields_set: item.description = payload.description
    if payload.status is not None: item.status = payload.status
    db.commit(); return {"data": {"template": template_row(db, item)}}


@router.put("/api/promotion/templates/{template_id}/integrations")
def update_template_integrations(
    template_id: str,
    payload: PromotionTemplateIntegrationsUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    item = _template(db, template_id, current_user)
    _set_template_integrations(db, item, payload.integration_ids, current_user)
    db.commit()
    db.refresh(item)
    return {"data": {"template": template_row(db, item)}}


@router.get("/api/promotion/templates/{template_id}/preview", response_class=HTMLResponse)
def preview_template(
    template_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    lang: str | None = None,
    device: Literal["desktop", "tablet", "mobile"] = "desktop",
) -> HTMLResponse:
    item = _template(db, template_id, current_user)
    policy = _runtime_template_policy(db, current_user.id)
    runtime_integrations = active_template_integrations(db, item.id)
    preview_root = f"/api/promotion/templates/{entity_id(item)}/preview/"
    preview_token = _preview_asset_token(item)
    asset_root = f"{preview_root}assets/_signed/{preview_token}/"
    manifest = item.manifest_json or {}
    default_locale = str(manifest.get("defaultLocale") or "en")
    supported_locales = list(manifest.get("supportedLocales") or [default_locale])
    requested_locale = lang.replace("_", "-") if lang else default_locale
    if requested_locale not in supported_locales:
        requested_locale = default_locale
    resolved_locale, localized_copy = _locale_copy(
        db, item, requested_locale, default_locale
    )
    html = _localize_template_html(item.index_html, resolved_locale, localized_copy)
    html = re.sub(r'(["\'])/assets/', rf'\1{asset_root}assets/', html)
    html = _apply_viewport_policy(html, policy)
    preview_config = json.dumps(
        {
            "previewMode": True,
            "previewDevice": device,
            "defaultLocale": default_locale,
            "resolvedLocale": resolved_locale,
            "supportedLocales": supported_locales,
            "localizedCopy": localized_copy,
            "inAppBrowserMode": "guide_external",
            "templatePolicy": policy,
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    preview_status_url = f"{preview_root}pairing-status"
    preview_pairing = json.dumps(
        {
            "data": {
                "pairing": {
                    "pairingCode": "48271639",
                    "attemptId": "4780486454931999",
                    "pairingStatus": "code_issued",
                    "expiresAt": iso(utcnow() + timedelta(minutes=3)),
                    "statusUrl": preview_status_url,
                    "cancelUrl": preview_status_url,
                    "statusToken": preview_token,
                    "statusTokenHeader": "Authorization",
                    "statusTokenScheme": "Bearer",
                    "preview": True,
                }
            }
        },
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    component_kit = (manifest.get("requirements") or {}).get("componentKit")
    component_runtime = (
        f'<script src="/api/public/promotion/account-link-elements.js?preview={preview_token}" defer></script>'
        if component_kit == "account-link-elements/v1"
        else ""
    )
    preview_parent_origin = json.dumps(_request_origin(request))
    preview_runtime = (
        f'<script type="application/json" id="promotion-runtime-config">{preview_config}</script>'
        "<script>"
        f"const PROMOTION_PREVIEW_PAIRING={preview_pairing};"
        f"const PROMOTION_PREVIEW_PARENT_ORIGIN={preview_parent_origin};"
        "const PROMOTION_PREVIEW_STATES={"
        "code_issued:{state:'pairing',accountState:'pairing',pairingStatus:'code_issued',verified:false,initializationStatus:'pending'},"
        "waiting_phone:{state:'pairing',accountState:'pairing',pairingStatus:'waiting_phone',verified:false,initializationStatus:'pending'},"
        "reconnecting:{state:'pairing',accountState:'pairing',pairingStatus:'reconnecting',verified:false,initializationStatus:'pending'},"
        "verified_syncing:{state:'syncing',accountState:'linked_offline',pairingStatus:'verified',verified:true,initializationStatus:'syncing'},"
        "ready:{state:'ready',accountState:'linked_offline',pairingStatus:'verified',verified:true,initializationStatus:'ready'},"
        "failed:{state:'failed',accountState:'failed',pairingStatus:'failed',verified:false,initializationStatus:'failed'},"
        "expired:{state:'expired',accountState:'pairing',pairingStatus:'expired',verified:false,initializationStatus:'pending'},"
        "cancelled:{state:'cancelled',accountState:'pairing',pairingStatus:'cancelled',verified:false,initializationStatus:'pending'}};"
        "let promotionPreviewState='code_issued';"
        "const promotionPreviewResponse=value=>new Response(JSON.stringify(value),"
        "{status:200,headers:{'Content-Type':'application/json'}});"
        "const promotionPreviewData=()=>({...PROMOTION_PREVIEW_STATES[promotionPreviewState],nextPollAfterMs:1000,preview:true});"
        "const setPromotionPreviewState=state=>{if(!PROMOTION_PREVIEW_STATES[state])return;promotionPreviewState=state;window.dispatchEvent(new CustomEvent('promotion-preview-state-change',{detail:promotionPreviewData()}))};"
        "addEventListener('message',event=>{if(event.source!==window.parent||event.origin!==PROMOTION_PREVIEW_PARENT_ORIGIN||event.data?.type!=='promotion-preview:set-state')return;setPromotionPreviewState(String(event.data.state||''))});"
        "document.addEventListener('account-link-pairing-started',()=>{if(window.parent!==window)window.parent.postMessage({type:'promotion-preview:pairing-started'},PROMOTION_PREVIEW_PARENT_ORIGIN)});"
        "document.addEventListener('account-link-reset',()=>{promotionPreviewState='code_issued';if(window.parent!==window)window.parent.postMessage({type:'promotion-preview:reset'},PROMOTION_PREVIEW_PARENT_ORIGIN)});"
        "window.PromotionBridge={version:'promotion-browser-bridge/v2',"
        "submitPhone:async()=>promotionPreviewResponse(PROMOTION_PREVIEW_PAIRING),"
        "getPairingStatus:async()=>promotionPreviewResponse({data:promotionPreviewData()}),"
        "cancelPairing:async()=>{setPromotionPreviewState('cancelled');return promotionPreviewResponse({data:promotionPreviewData()})}};"
        "</script>"
        f"{component_runtime}"
        f"<script>{LANDING_GUARD_JS}</script>"
    )
    html = _inject_after_head_open(
        html,
        f'<base href="{asset_root}">{preview_runtime}',
    )
    html = inject_runtime_integrations(html, runtime_integrations)
    # Without allow-same-origin, uploaded template code cannot inherit the
    # control-plane origin, cookies, or storage. The signed asset path above
    # lets the opaque sandbox fetch only this preview bundle without a login
    # cookie. Scheme sources are required because an opaque origin never
    # matches CSP's 'self', including when Vite proxies the API in development.
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": _sandbox_csp(
                request,
                preview=True,
                integrations=runtime_integrations,
            ),
            "Cache-Control": "private, no-store",
            "Content-Language": resolved_locale,
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/api/promotion/templates/{template_id}/preview/pairing-status")
def preview_pairing_status(
    template_id: str,
    db: DbSession,
    token: str = Query(min_length=20, max_length=1000),
) -> JSONResponse:
    item = db.scalar(
        select(PromotionTemplate).where(
            identifier_filter(PromotionTemplate, template_id),
            PromotionTemplate.archived_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=404)
    _verify_preview_asset_token(entity_id(item), token)
    return JSONResponse(
        {
            "data": {
                "state": "ready",
                "accountState": "linked_offline",
                "pairingStatus": "verified",
                "verified": True,
                "preview": True,
            }
        },
        headers={
            "Access-Control-Allow-Origin": "null",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/api/promotion/templates/{template_id}/preview/assets/_signed/{preview_token}/{asset_path:path}"
)
def signed_preview_asset(
    template_id: str,
    preview_token: str,
    asset_path: str,
    db: DbSession,
) -> Response:
    item = db.scalar(
        select(PromotionTemplate).where(
            identifier_filter(PromotionTemplate, template_id),
            PromotionTemplate.archived_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=404)
    _verify_preview_asset_token(entity_id(item), preview_token)
    asset_root = (
        f"/api/promotion/templates/{entity_id(item)}/preview/assets/"
        f"_signed/{preview_token}/"
    )
    return _preview_asset_response(db, item, asset_path, asset_root)


@router.get("/api/promotion/templates/{template_id}/preview/assets/{asset_path:path}")
def preview_asset(template_id: str, asset_path: str, db: DbSession, current_user: CurrentUser) -> Response:
    item = _template(db, template_id, current_user)
    asset_root = f"/api/promotion/templates/{entity_id(item)}/preview/assets/"
    return _preview_asset_response(db, item, asset_path, asset_root)


@router.delete("/api/promotion/templates/{template_id}")
def archive_template(template_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _template(db, template_id, current_user)
    if db.scalar(select(func.count()).select_from(PromotionChannel).where(PromotionChannel.template_id == item.id, PromotionChannel.archived_at.is_(None))): raise HTTPException(status_code=409, detail="模板仍被推广渠道使用")
    item.status = "archived"; item.archived_at = utcnow(); db.commit(); return {"data": {"ok": True}}


def _resolve_channel_refs(db: DbSession, user, template_id: str | None, domain_id: str | None, pixel_id: str | None, current: PromotionChannel | None = None) -> tuple[int, int | None, int | None]:
    template_pk = current.template_id if current else None
    if template_id is not None:
        tpl = _template(db, template_id, user)
        if tpl.status != "active": raise HTTPException(status_code=409, detail="模板未启用")
        template_pk = tpl.id
    if template_pk is None: raise HTTPException(status_code=422, detail="必须选择模板")
    domain_pk = current.domain_id if current else None
    if domain_id is not None:
        domain = db.scalar(select(DomainRecord).where(identifier_filter(DomainRecord, domain_id), DomainRecord.archived_at.is_(None)))
        if domain is not None and user.role != "admin" and domain.created_by != user.id: domain = None
        if domain is None: raise HTTPException(status_code=404, detail="域名不存在")
        if not (
            domain.enabled
            and domain.registration_status == "active"
            and domain.dns_status == "verified"
            and domain.ssl_status == "verified"
            and domain.hosting_status == "active"
        ):
            raise HTTPException(status_code=409, detail="域名尚未完成接入验证，不能绑定渠道")
        domain_pk = domain.id
    pixel_pk = current.pixel_id if current else None
    if pixel_id is not None:
        pixel = db.scalar(select(MetaPixel).where(identifier_filter(MetaPixel, pixel_id), MetaPixel.archived_at.is_(None)))
        if pixel is not None and user.role != "admin" and pixel.created_by != user.id: pixel = None
        if pixel is None: raise HTTPException(status_code=404, detail="Pixel 不存在")
        if not pixel.enabled:
            raise HTTPException(status_code=409, detail="Pixel 已停用，不能绑定渠道")
        pixel_pk = pixel.id
    return template_pk, domain_pk, pixel_pk


def _validate_channel_contract(
    db: DbSession,
    *,
    template_id: int,
    protocol_node_id: int | None,
    protocol_pool_id: int | None,
    pixel_id: int | None,
    browser_enabled: bool,
    capi_enabled: bool,
) -> None:
    template = db.get(PromotionTemplate, template_id)
    manifest = template.manifest_json if template else {}
    pairing_contract = (manifest.get("requirements") or {}).get(
        "pairingContract", "promotion-public-pairing/v1"
    )
    if pairing_contract != "promotion-public-pairing/v1":
        raise HTTPException(status_code=409, detail="模板与当前账号接入契约不兼容")
    if protocol_node_id is not None:
        nodes = [db.get(ProtocolNode, protocol_node_id)]
    elif protocol_pool_id is not None:
        nodes = list(
            db.scalars(
                select(ProtocolNode)
                .join(
                    ProtocolPoolMember,
                    ProtocolPoolMember.protocol_node_id == ProtocolNode.id,
                )
                .where(
                    ProtocolPoolMember.pool_id == protocol_pool_id,
                    ProtocolPoolMember.enabled.is_(True),
                    ProtocolNode.archived_at.is_(None),
                )
            ).all()
        )
    else:
        nodes = []
    if not nodes or any(node is None or node.protocol_type != "baileys" for node in nodes):
        raise HTTPException(status_code=409, detail="协议路由不支持模板声明的账号接入能力")
    if browser_enabled or capi_enabled:
        pixel = db.get(MetaPixel, pixel_id) if pixel_id else None
        if pixel is None or not pixel.enabled or pixel.archived_at is not None:
            raise HTTPException(status_code=422, detail="启用 Meta 事件前必须绑定可用 Pixel")
        if capi_enabled and not pixel.capi_token_ciphertext:
            raise HTTPException(status_code=422, detail="启用 Meta CAPI 前必须配置 CAPI Token")


def _resolve_channel_account_group(
    db: DbSession,
    user,
    account_group_id: str | None,
    current: PromotionChannel | None = None,
) -> int | None:
    if account_group_id is None:
        return current.account_group_id if current else None
    owner_id = current.created_by if current else user.id
    group = db.scalar(
        select(AccountGroup).where(
            identifier_filter(AccountGroup, account_group_id),
            AccountGroup.created_by == owner_id,
            AccountGroup.archived_at.is_(None),
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="账号入库分组不存在")
    return group.id


def _resolve_channel_protocol_route(
    db: DbSession,
    user,
    protocol_node_id: str | None,
    protocol_pool_id: str | None,
    current: PromotionChannel | None = None,
) -> tuple[int | None, int | None]:
    owner_id = current.created_by if current else user.id
    if protocol_node_id and protocol_pool_id:
        raise HTTPException(
            status_code=422, detail="渠道只能绑定协议节点或协议池中的一种"
        )
    if protocol_node_id:
        node = db.scalar(
            select(ProtocolNode).where(
                identifier_filter(ProtocolNode, protocol_node_id),
                ProtocolNode.created_by == owner_id,
                ProtocolNode.archived_at.is_(None),
            )
        )
        if node is None:
            raise HTTPException(status_code=404, detail="协议节点不存在")
        return node.id, None
    if protocol_pool_id:
        pool = db.scalar(
            select(ProtocolPool).where(
                identifier_filter(ProtocolPool, protocol_pool_id),
                ProtocolPool.created_by == owner_id,
                ProtocolPool.archived_at.is_(None),
            )
        )
        if pool is None:
            raise HTTPException(status_code=404, detail="协议池不存在")
        return None, pool.id
    if current is not None:
        if current.protocol_node_id is not None or current.protocol_pool_id is not None:
            return current.protocol_node_id, current.protocol_pool_id
    node = db.scalar(
        select(ProtocolNode)
        .where(
            ProtocolNode.created_by == owner_id,
            ProtocolNode.archived_at.is_(None),
        )
        .order_by(ProtocolNode.id)
        .limit(1)
    )
    if node is None:
        from app.services.protocol_nodes import select_ingress_protocol

        node = select_ingress_protocol(db, owner_id)
    return node.id, None


@router.get("/api/promotion/channels")
def list_channels(db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(PromotionChannel).where(PromotionChannel.archived_at.is_(None))
    if current_user.role != "admin": statement = statement.where(PromotionChannel.created_by == current_user.id)
    items = db.scalars(statement.order_by(PromotionChannel.created_at.desc())).all(); return {"data": {"rows": [channel_row(db, x) for x in items], "total": len(items)}}


@router.post("/api/promotion/channels", status_code=status.HTTP_201_CREATED)
def create_channel(payload: PromotionChannelCreate, db: DbSession, current_user: CurrentUser) -> dict:
    tpl, dom, pix = _resolve_channel_refs(db, current_user, payload.template_id, payload.domain_id, payload.pixel_id)
    account_group_id = _resolve_channel_account_group(
        db, current_user, payload.account_group_id
    )
    protocol_node_id, protocol_pool_id = _resolve_channel_protocol_route(
        db,
        current_user,
        payload.protocol_node_id,
        payload.protocol_pool_id,
    )
    if get_settings().environment != "development" and dom is None:
        raise HTTPException(status_code=422, detail="生产环境渠道必须绑定已验证域名")
    if payload.status == "active" and account_group_id is None:
        raise HTTPException(status_code=422, detail="启用渠道前必须选择账号入库分组")
    template = db.get(PromotionTemplate, tpl); supported = (template.manifest_json or {}).get("supportedLocales", [])
    if payload.locale_mode == "fixed" and (not payload.locale or payload.locale not in supported): raise HTTPException(status_code=422, detail="固定 locale 必须属于模板 supportedLocales")
    browser_enabled = bool(pix and payload.meta_browser_pixel_enabled)
    _validate_channel_contract(
        db,
        template_id=tpl,
        protocol_node_id=protocol_node_id,
        protocol_pool_id=protocol_pool_id,
        pixel_id=pix,
        browser_enabled=browser_enabled,
        capi_enabled=payload.meta_capi_enabled,
    )
    item = PromotionChannel(public_id=new_public_id("pchn"), channel_type=payload.channel_type, name=payload.name, country_code=payload.country_code, template_id=tpl, domain_id=dom, subdomain_prefix=payload.subdomain_prefix or "", slug=payload.slug, pixel_id=pix, account_group_id=account_group_id, protocol_node_id=protocol_node_id, protocol_pool_id=protocol_pool_id, route_version=1, meta_browser_pixel_enabled=browser_enabled, meta_capi_enabled=payload.meta_capi_enabled, meta_event_mapping_json=payload.meta_event_mapping, in_app_browser_mode=payload.in_app_browser_mode, new_account_marketing_enabled=payload.new_account_marketing_enabled, locale_mode=payload.locale_mode, locale=payload.locale, status=payload.status, launch_at=payload.launch_at, created_by=current_user.id)
    db.add(item)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(status_code=409, detail="该域名和子域名下的推广渠道 slug 已存在") from None
    db.refresh(item); return {"data": {"channel": channel_row(db, item)}}


@router.get("/api/promotion/channels/{channel_id}")
def get_channel(channel_id: str, db: DbSession, current_user: CurrentUser) -> dict: return {"data": {"channel": channel_row(db, _channel(db, channel_id, current_user))}}


@router.patch("/api/promotion/channels/{channel_id}")
def update_channel(channel_id: str, payload: PromotionChannelUpdate, db: DbSession, current_user: CurrentUser) -> dict:
    item = _channel(db, channel_id, current_user); tpl, dom, pix = _resolve_channel_refs(db, current_user, payload.template_id, payload.domain_id if "domain_id" in payload.model_fields_set else None, payload.pixel_id if "pixel_id" in payload.model_fields_set else None, item)
    if payload.name is not None: item.name = payload.name
    if payload.country_code is not None: item.country_code = payload.country_code
    if payload.slug is not None: item.slug = payload.slug
    if "subdomain_prefix" in payload.model_fields_set: item.subdomain_prefix = payload.subdomain_prefix or ""
    if payload.status is not None: item.status = payload.status
    if payload.locale_mode is not None: item.locale_mode = payload.locale_mode
    if "locale" in payload.model_fields_set: item.locale = payload.locale
    if "launch_at" in payload.model_fields_set: item.launch_at = payload.launch_at
    item.template_id = tpl
    template = db.get(PromotionTemplate, tpl); supported = (template.manifest_json or {}).get("supportedLocales", [])
    if item.locale_mode == "fixed" and (not item.locale or item.locale not in supported): raise HTTPException(status_code=422, detail="固定 locale 必须属于模板 supportedLocales")
    if "domain_id" in payload.model_fields_set: item.domain_id = dom if payload.domain_id else None
    if get_settings().environment != "development" and item.domain_id is None:
        raise HTTPException(status_code=422, detail="生产环境渠道必须绑定已验证域名")
    if "pixel_id" in payload.model_fields_set:
        item.pixel_id = pix if payload.pixel_id else None
        if item.pixel_id is None:
            item.meta_browser_pixel_enabled = False
            item.meta_capi_enabled = False
    if payload.meta_browser_pixel_enabled is not None:
        item.meta_browser_pixel_enabled = payload.meta_browser_pixel_enabled
    if payload.meta_capi_enabled is not None:
        item.meta_capi_enabled = payload.meta_capi_enabled
    if payload.meta_event_mapping is not None:
        item.meta_event_mapping_json = payload.meta_event_mapping
    if payload.in_app_browser_mode is not None:
        item.in_app_browser_mode = payload.in_app_browser_mode
    if payload.new_account_marketing_enabled is not None:
        item.new_account_marketing_enabled = payload.new_account_marketing_enabled
    if item.pixel_id is None:
        item.meta_browser_pixel_enabled = False
    if "account_group_id" in payload.model_fields_set:
        item.account_group_id = (
            _resolve_channel_account_group(
                db, current_user, payload.account_group_id, item
            )
            if payload.account_group_id
            else None
        )
    route_fields = {"protocol_node_id", "protocol_pool_id"}
    if payload.model_fields_set.intersection(route_fields):
        requested_node = (
            payload.protocol_node_id
            if "protocol_node_id" in payload.model_fields_set
            else None
        )
        requested_pool = (
            payload.protocol_pool_id
            if "protocol_pool_id" in payload.model_fields_set
            else None
        )
        if not requested_node and not requested_pool:
            raise HTTPException(status_code=422, detail="渠道必须绑定协议节点或协议池")
        next_node_id, next_pool_id = _resolve_channel_protocol_route(
            db,
            current_user,
            requested_node,
            requested_pool,
            item,
        )
        if (
            item.protocol_node_id != next_node_id
            or item.protocol_pool_id != next_pool_id
        ):
            item.protocol_node_id = next_node_id
            item.protocol_pool_id = next_pool_id
            item.route_version = int(item.route_version or 1) + 1
    if item.status == "active" and item.account_group_id is None:
        raise HTTPException(status_code=422, detail="启用渠道前必须选择账号入库分组")
    if item.protocol_node_id is None and item.protocol_pool_id is None:
        raise HTTPException(status_code=422, detail="启用渠道前必须配置协议路由")
    _validate_channel_contract(
        db,
        template_id=item.template_id,
        protocol_node_id=item.protocol_node_id,
        protocol_pool_id=item.protocol_pool_id,
        pixel_id=item.pixel_id,
        browser_enabled=item.meta_browser_pixel_enabled,
        capi_enabled=item.meta_capi_enabled,
    )
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(status_code=409, detail="该域名和子域名下的推广渠道 slug 已存在") from None
    return {"data": {"channel": channel_row(db, item)}}


@router.delete("/api/promotion/channels/{channel_id}")
def archive_channel(channel_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    item = _channel(db, channel_id, current_user); item.status = "archived"; item.archived_at = utcnow(); db.commit(); return {"data": {"ok": True}}


@router.get("/api/promotion/channels/{channel_id}/meta-deliveries")
def list_channel_meta_deliveries(
    channel_id: str,
    db: DbSession,
    current_user: CurrentUser,
    delivery_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=200),
) -> dict:
    channel = _channel(db, channel_id, current_user)
    statement = select(MetaConversionDelivery).where(
        MetaConversionDelivery.channel_id == channel.id
    )
    if delivery_status:
        if delivery_status not in {
            "pending", "sending", "retry", "delivered", "failed", "skipped"
        }:
            raise HTTPException(status_code=422, detail="Meta 投递状态不正确")
        statement = statement.where(
            MetaConversionDelivery.status == delivery_status
        )
    total = int(
        db.scalar(
            select(func.count())
            .select_from(MetaConversionDelivery)
            .where(MetaConversionDelivery.channel_id == channel.id)
        )
        or 0
    )
    rows = list(
        db.scalars(
            statement.order_by(MetaConversionDelivery.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    counts = dict(
        db.execute(
            select(
                MetaConversionDelivery.status,
                func.count(MetaConversionDelivery.id),
            )
            .where(MetaConversionDelivery.channel_id == channel.id)
            .group_by(MetaConversionDelivery.status)
        ).all()
    )
    return {
        "data": {
            "rows": [
                {
                    "id": entity_id(row),
                    "eventName": row.event_name,
                    "eventId": row.event_id,
                    "eventTime": iso(row.event_time),
                    "status": row.status,
                    "attemptCount": row.attempt_count,
                    "nextAttemptAt": iso(row.next_attempt_at),
                    "deliveredAt": iso(row.delivered_at),
                    "providerTraceId": row.provider_trace_id,
                    "lastError": row.last_error,
                    "createdAt": iso(row.created_at),
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "summary": {
                key: int(counts.get(key, 0))
                for key in (
                    "pending", "sending", "retry", "delivered", "failed", "skipped"
                )
            },
        }
    }


def _public_channel(
    db: DbSession,
    slug: str,
    request: Request,
    *,
    require_active: bool = True,
) -> PromotionChannel:
    request_host = (request.url.hostname or "").lower().rstrip(".")
    settings = get_settings()
    local_preview = settings.environment == "development" and request_host in {
        "localhost",
        "127.0.0.1",
        "::1",
        "testserver",
        # Vite's Docker proxy rewrites Host to the Compose service name.
        "api",
    }
    configured_backend_hosts = {
        (urlsplit(origin).hostname or "").lower().rstrip(".")
        for origin in settings.cors_origins
    }
    private_development_host = False
    if settings.environment == "development":
        try:
            address = ipaddress.ip_address(request_host)
            private_development_host = address.is_private or address.is_loopback
        except ValueError:
            pass
    authenticated_preview_host = (
        request_host in configured_backend_hosts or private_development_host
    )
    statement = select(PromotionChannel).where(
        PromotionChannel.slug == slug,
        PromotionChannel.archived_at.is_(None),
    )
    if require_active:
        statement = statement.where(PromotionChannel.status == "active")
    # A ready promotion hostname is always authoritative, even for a signed-in
    # backend user. This prevents an authenticated preview from crossing from
    # one real promotion domain into another domain's same-slug channel.
    host_candidates = [request_host]
    requested_subdomain = ""
    if "." in request_host:
        first_label, base_host = request_host.split(".", 1)
        host_candidates.append(base_host)
    domains = db.scalars(
        select(DomainRecord).where(
            DomainRecord.hostname.in_(host_candidates),
            DomainRecord.archived_at.is_(None),
            DomainRecord.enabled.is_(True),
            DomainRecord.registration_status == "active",
            DomainRecord.dns_status == "verified",
            DomainRecord.ssl_status == "verified",
            DomainRecord.hosting_status == "active",
        )
    ).all()
    domain = next((row for row in domains if row.hostname == request_host), None)
    if domain is None and "." in request_host:
        domain = next((row for row in domains if row.hostname == base_host), None)
        if domain is not None:
            requested_subdomain = first_label
    preview_user = (
        get_optional_current_user(request, db)
        if domain is None and authenticated_preview_host
        else None
    )
    preview_mode = domain is None and (local_preview or preview_user is not None)
    if preview_mode:
        if preview_user is not None and preview_user.role != "admin":
            statement = statement.where(
                PromotionChannel.created_by == preview_user.id
            )
        requested_channel = request.query_params.get("channelId")
        if requested_channel:
            statement = statement.where(
                identifier_filter(PromotionChannel, requested_channel)
            )
        items = db.scalars(statement.limit(2)).all()
        if len(items) > 1:
            raise HTTPException(
                status_code=409,
                detail="预览存在同名 slug，请使用 channelId 指定渠道",
            )
        item = items[0] if items else None
    else:
        if domain is None:
            raise HTTPException(status_code=404, detail="推广域名不可用")
        item = db.scalar(
            statement.where(
                PromotionChannel.domain_id == domain.id,
                PromotionChannel.subdomain_prefix == requested_subdomain,
            )
        )
    if item is None or (
        item.launch_at
        and item.launch_at.replace(tzinfo=item.launch_at.tzinfo or UTC) > utcnow()
    ):
        raise HTTPException(status_code=404, detail="推广渠道不存在或尚未上线")
    if not preview_mode and domain is not None and not (
        domain.archived_at is None
        and domain.enabled
        and domain.registration_status == "active"
        and domain.dns_status == "verified"
        and domain.ssl_status == "verified"
        and domain.hosting_status == "active"
    ):
        raise HTTPException(status_code=404, detail="推广域名不可用")
    return item


def _resolved_locale(channel: PromotionChannel, template: PromotionTemplate, requested: str | None) -> tuple[str, str, list[str]]:
    manifest = template.manifest_json or {}; default = str(manifest.get("defaultLocale") or "en"); supported = list(manifest.get("supportedLocales") or [default])
    if channel.locale_mode == "fixed" and channel.locale in supported: return channel.locale, default, supported
    normalized = requested.replace("_", "-") if requested else None
    if normalized in supported: return normalized, default, supported
    country_default = COUNTRY_DEFAULT_LOCALE.get(channel.country_code, default)
    if country_default in supported: return country_default, default, supported
    base = country_default.split("-", 1)[0]
    matched = next((locale for locale in supported if locale.split("-", 1)[0] == base), None)
    return matched or default, default, supported


def _locale_copy(
    db: DbSession,
    template: PromotionTemplate,
    requested_locale: str,
    default_locale: str,
) -> tuple[str, dict[str, str]]:
    """Load one flat, bounded locale map and fall back without failing render."""
    manifest = template.manifest_json or {}
    i18n = manifest.get("i18n") if isinstance(manifest.get("i18n"), dict) else {}
    path_pattern = str(i18n.get("path") or "locales/{locale}.json")
    fallback_locale = str(i18n.get("fallbackLocale") or default_locale).replace(
        "_", "-"
    )
    candidates = list(
        dict.fromkeys((requested_locale, fallback_locale, default_locale))
    )
    for locale in candidates:
        path = path_pattern.replace("{locale}", locale)
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts:
            continue
        asset = db.scalar(
            select(PromotionAsset).where(
                PromotionAsset.template_id == template.id,
                PromotionAsset.path == normalized.as_posix(),
            )
        )
        if asset is None or asset.size > MAX_LOCALE_ASSET_BYTES:
            continue
        try:
            raw_copy = json.loads(asset.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw_copy, dict):
            continue
        localized_copy: dict[str, str] = {}
        for raw_key, raw_value in raw_copy.items():
            key = str(raw_key)
            if (
                len(localized_copy) >= MAX_LOCALIZED_COPY_ITEMS
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", key)
                or not isinstance(raw_value, str)
                or len(raw_value) > MAX_LOCALIZED_COPY_VALUE
            ):
                continue
            localized_copy[key] = raw_value
        if localized_copy:
            return locale, localized_copy
    return default_locale, {}


def _set_opening_tag_attribute(opening: str, name: str, value: str) -> str:
    escaped = html_lib.escape(value, quote=True)
    pattern = re.compile(
        rf"(\s){re.escape(name)}\s*=\s*([\"']).*?\2", re.I | re.S
    )
    if pattern.search(opening):
        return pattern.sub(
            lambda match: f'{match.group(1)}{name}="{escaped}"',
            opening,
            count=1,
        )
    suffix = "/>" if opening.endswith("/>") else ">"
    return opening[: -len(suffix)] + f' {name}="{escaped}"' + suffix


def _localize_template_html(
    html: str, locale: str, localized_copy: dict[str, str]
) -> str:
    """Apply locale content before the response reaches the browser."""
    direction = "rtl" if locale.split("-", 1)[0].lower() in RTL_LANGUAGE_BASES else "ltr"
    html_match = re.search(r"<html\b[^>]*>", html, re.I | re.S)
    if html_match:
        opening = _set_opening_tag_attribute(html_match.group(0), "lang", locale)
        opening = _set_opening_tag_attribute(opening, "dir", direction)
        html = html[: html_match.start()] + opening + html[html_match.end() :]

    element_pattern = re.compile(
        r"(?P<open><(?P<tag>[A-Za-z][A-Za-z0-9:-]*)\b"
        r"(?P<attrs>[^>]*\bdata-copy\s*=\s*(?P<quote>[\"'])"
        r"(?P<key>[^\"']{1,128})(?P=quote)[^>]*)>)"
        r"(?P<body>.*?)"
        r"(?P<close></(?P=tag)\s*>)",
        re.I | re.S,
    )

    def replace_element(match: re.Match[str]) -> str:
        value = localized_copy.get(match.group("key"))
        if value is None:
            return match.group(0)
        return match.group("open") + html_lib.escape(value) + match.group("close")

    html = element_pattern.sub(replace_element, html)

    for data_name, target_name in (
        ("placeholder", "placeholder"),
        ("aria-label", "aria-label"),
        ("title", "title"),
        ("value", "value"),
        ("content", "content"),
    ):
        tag_pattern = re.compile(
            rf"<(?P<tag>[A-Za-z][A-Za-z0-9:-]*)\b"
            rf"(?P<attrs>[^>]*\bdata-copy-{re.escape(data_name)}\s*=\s*"
            rf"(?P<quote>[\"'])(?P<key>[^\"']{{1,128}})(?P=quote)[^>]*)>",
            re.I | re.S,
        )

        def replace_attribute(match: re.Match[str]) -> str:
            value = localized_copy.get(match.group("key"))
            if value is None:
                return match.group(0)
            return _set_opening_tag_attribute(match.group(0), target_name, value)

        html = tag_pattern.sub(replace_attribute, html)

    title = localized_copy.get("title")
    if title is not None:
        escaped_title = html_lib.escape(title)
        if re.search(r"<title\b[^>]*>.*?</title\s*>", html, re.I | re.S):
            html = re.sub(
                r"<title\b[^>]*>.*?</title\s*>",
                lambda _match: f"<title>{escaped_title}</title>",
                html,
                count=1,
                flags=re.I | re.S,
            )
        else:
            html = _inject_after_head_open(html, f"<title>{escaped_title}</title>")
    return html


@router.get("/api/public/promotion/channels/{slug}")
def public_channel(slug: str, request: Request, db: DbSession, lang: str | None = None) -> dict:
    item = _public_channel(db, slug, request); tpl = db.get(PromotionTemplate, item.template_id); pixel = db.get(MetaPixel, item.pixel_id) if item.pixel_id else None; token = _session_token(item)
    if pixel is not None and (not pixel.enabled or pixel.archived_at is not None):
        pixel = None
    from app.services.meta_conversions import normalized_meta_event_mapping
    policy = _runtime_template_policy(db, item.created_by)
    resolved, default, supported = _resolved_locale(item, tpl, lang)
    return {"data": {"channel": {"id": entity_id(item), "type": item.channel_type, "name": item.name, "countryCode": item.country_code, "slug": item.slug, "localeMode": item.locale_mode}, "template": {"id": entity_id(tpl), "version": tpl.version, "manifest": tpl.manifest_json}, "templatePolicy": policy, "meta": {"datasetId": pixel.dataset_id if pixel else None, "browserEnabled": bool(pixel and item.meta_browser_pixel_enabled), "capiEnabled": bool(pixel and item.meta_capi_enabled), "eventMapping": normalized_meta_event_mapping(item.meta_event_mapping_json)}, "inAppBrowserMode": item.in_app_browser_mode, "countryCode": item.country_code, "defaultLocale": default, "supportedLocales": supported, "resolvedLocale": resolved, "renderUrl": f"/api/public/promotion/channels/{slug}/render", "fissionRenderUrl": f"/api/public/promotion/channels/{slug}/fission/render", "assetBaseUrl": f"/api/public/promotion/channels/{slug}/assets/", "eventUrl": f"/api/public/promotion/channels/{slug}/events", "pairingStartUrl": f"/api/public/promotion/channels/{slug}/pairing/start", "sessionToken": token, "sessionExpiresIn": 1800, "rateLimitPolicy": "reserved", "serverTimestamp": utcnow().isoformat()}}


def _render_html(
    db: DbSession,
    channel: PromotionChannel,
    template: PromotionTemplate,
    html: str,
    lang: str | None,
    pixel_dataset_id: str | None = None,
    traffic_source: str = "direct",
    template_policy: dict | None = None,
) -> tuple[str, str, list[ActivePromotionIntegration]]:
    slug = channel.slug
    requested_locale, default, supported = _resolved_locale(channel, template, lang)
    resolved, localized_copy = _locale_copy(
        db, template, requested_locale, default
    )
    html = _localize_template_html(html, resolved, localized_copy)
    runtime_integrations = active_template_integrations(db, template.id)
    from app.services.meta_conversions import normalized_meta_event_mapping

    config = json.dumps({"eventUrl": f"/api/public/promotion/channels/{slug}/events", "pairingStartUrl": f"/api/public/promotion/channels/{slug}/pairing/start", "sessionToken": _session_token(channel, traffic_source), "trafficSource": traffic_source, "countryCode": channel.country_code, "defaultLocale": default, "supportedLocales": supported, "resolvedLocale": resolved, "localizedCopy": localized_copy, "pixelDatasetId": pixel_dataset_id, "meta": {"datasetId": pixel_dataset_id, "browserEnabled": bool(pixel_dataset_id and channel.meta_browser_pixel_enabled), "eventMapping": normalized_meta_event_mapping(channel.meta_event_mapping_json)}, "inAppBrowserMode": channel.in_app_browser_mode, "templatePolicy": template_policy or {}}, ensure_ascii=False).replace("<", "\\u003c")
    html = _apply_viewport_policy(html, template_policy or {})
    base = f'<base href="/api/public/promotion/channels/{slug}/assets/">'
    runtime = (
        f'<script type="application/json" id="promotion-runtime-config">{config}</script>'
        '<script src="/api/public/promotion/tracker.js" defer></script>'
        '<script src="/api/public/promotion/guard.js" defer></script>'
        + (
            '<script src="/api/public/promotion/account-link-elements.js" defer></script>'
            if ((template.manifest_json or {}).get("requirements") or {}).get("componentKit")
            == "account-link-elements/v1"
            else ""
        )
    )
    html = re.sub(r'(["\'])/assets/', rf'\1/api/public/promotion/channels/{slug}/assets/assets/', html)
    if re.search(r"<head\b[^>]*>", html, re.I):
        html = _inject_after_head_open(html, base)
        rendered = re.sub(r"</head\s*>", runtime + "</head>", html, count=1, flags=re.I) if re.search(r"</head\s*>", html, re.I) else html + runtime
        return inject_runtime_integrations(rendered, runtime_integrations), resolved, runtime_integrations
    rendered = inject_runtime_integrations(base + runtime + html, runtime_integrations)
    return rendered, resolved, runtime_integrations


@router.get("/api/public/promotion/channels/{slug}/render", response_class=HTMLResponse)
def render_channel(slug: str, request: Request, db: DbSession, lang: str | None = None) -> HTMLResponse:
    item = _public_channel(db, slug, request)
    tpl = db.get(PromotionTemplate, item.template_id)
    pixel = db.get(MetaPixel, item.pixel_id) if item.pixel_id else None
    if pixel is not None and (not pixel.enabled or pixel.archived_at is not None):
        pixel = None
    policy = _runtime_template_policy(db, item.created_by)
    html, resolved_locale, runtime_integrations = _render_html(
            db,
            item,
            tpl,
            tpl.index_html,
            lang,
            pixel.dataset_id if pixel else None,
            template_policy=policy,
        )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Language": resolved_locale,
            "Content-Security-Policy": _sandbox_csp(
                request,
                integrations=runtime_integrations,
            ),
            "Referrer-Policy": "strict-origin-when-cross-origin",
        },
    )


@router.get(
    "/api/public/promotion/channels/{slug}/fission/render",
    response_class=HTMLResponse,
)
def render_fission_channel(
    slug: str, request: Request, db: DbSession, lang: str | None = None
) -> HTMLResponse:
    item = _public_channel(db, slug, request)
    tpl = db.get(PromotionTemplate, item.template_id)
    pixel = db.get(MetaPixel, item.pixel_id) if item.pixel_id else None
    if pixel is not None and (not pixel.enabled or pixel.archived_at is not None):
        pixel = None
    policy = _runtime_template_policy(db, item.created_by)
    html, resolved_locale, runtime_integrations = _render_html(
            db,
            item,
            tpl,
            tpl.index_html,
            lang,
            pixel.dataset_id if pixel else None,
            "fission",
            policy,
        )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Language": resolved_locale,
            "Content-Security-Policy": _sandbox_csp(
                request,
                integrations=runtime_integrations,
            ),
            "Referrer-Policy": "strict-origin-when-cross-origin",
        },
    )


@router.get("/api/public/promotion/tracker.js")
def tracker_script() -> Response: return Response(TRACKER_JS, media_type="application/javascript", headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


@router.get("/api/public/promotion/account-link-elements.js")
def account_link_elements_script() -> Response:
    return Response(
        (PUBLIC_RUNTIME_DIR / "account-link-elements.js").read_bytes(),
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/public/promotion/guard.js")
def landing_guard_script() -> Response:
    return Response(
        LANDING_GUARD_JS,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/public/promotion/channels/{slug}/assets/{asset_path:path}")
def promotion_asset(slug: str, asset_path: str, request: Request, db: DbSession) -> Response:
    item = _public_channel(db, slug, request); normalized = PurePosixPath(asset_path)
    if normalized.is_absolute() or ".." in normalized.parts: raise HTTPException(status_code=404)
    asset = db.scalar(select(PromotionAsset).where(PromotionAsset.template_id == item.template_id, PromotionAsset.path == normalized.as_posix()))
    if asset is None: raise HTTPException(status_code=404)
    content = asset.content
    if asset.content_type in {"text/css", "application/javascript", "text/javascript"}:
        content = re.sub(rb'(["\'(])/assets/', rb'\1/api/public/promotion/channels/' + slug.encode() + rb'/assets/assets/', content)
    return Response(content, media_type=asset.content_type, headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff", "Access-Control-Allow-Origin": "*"})


@router.post("/api/public/promotion/channels/{slug}/events")
async def report_event(slug: str, request: Request, db: DbSession) -> JSONResponse:
    try: payload = PromotionEventInput.model_validate_json(await request.body())
    except ValidationError as exc: raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from None
    channel = _public_channel(db, slug, request)
    token_payload = _verify_session_token(channel, payload.session_token)
    existing = db.scalar(select(PromotionEvent).where(PromotionEvent.channel_id == channel.id, PromotionEvent.idempotency_key == payload.idempotency_key))
    if existing: return JSONResponse({"data": {"ok": True, "duplicate": True, "serverTimestamp": iso(existing.created_at)}}, headers={"Access-Control-Allow-Origin": "null"})
    if payload.event_type == "phone_submit" and not payload.phone: raise HTTPException(status_code=422, detail="phone_submit 必须包含手机号")
    now = utcnow(); occurred_at = parse_public_datetime(payload.occurred_at)
    occurred_ts = int(occurred_at.timestamp())
    if occurred_ts < int(token_payload["iat"]) - 300 or occurred_ts > int(token_payload["exp"]) + 300 or occurred_at > now + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="occurredAt 超出推广会话有效窗口")
    lead = None
    if payload.phone:
        lead = db.scalar(select(PromotionLead).where(PromotionLead.channel_id == channel.id, PromotionLead.phone_e164 == payload.phone))
        if lead: lead.last_seen_at = now; lead.submission_count += 1; lead.country_code = channel.country_code
        else:
            lead = PromotionLead(public_id=new_public_id("plead"), channel_id=channel.id, phone_e164=payload.phone, country_code=channel.country_code, first_seen_at=now, last_seen_at=now, submission_count=1)
            db.add(lead)
            db.flush()
    metadata = dict(payload.metadata)
    metadata["trafficSource"] = token_payload.get("trafficSource", "direct")
    event = PromotionEvent(public_id=new_public_id("pevt"), channel_id=channel.id, event_type=payload.event_type, idempotency_key=payload.idempotency_key, visitor_id=payload.visitor_id, lead_id=lead.id if lead else None, occurred_at=occurred_at, country_code=channel.country_code, metadata_json=metadata)
    db.add(event)
    from app.services.meta_conversions import (
        browser_event_descriptor,
        enqueue_meta_conversion,
    )

    enqueue_meta_conversion(
        db,
        channel=channel,
        event_key=payload.event_type,
        event_id=payload.idempotency_key,
        event_time=occurred_at,
        request=request,
        phone=payload.phone,
        visitor_id=payload.visitor_id,
        custom_data={"trafficSource": metadata["trafficSource"]},
    )
    meta_event = browser_event_descriptor(
        channel, payload.event_type, payload.idempotency_key
    )
    try: db.commit()
    except IntegrityError: db.rollback(); return JSONResponse({"data": {"ok": True, "duplicate": True, "serverTimestamp": now.isoformat()}}, headers={"Access-Control-Allow-Origin": "null"})
    return JSONResponse({"data": {"ok": True, "duplicate": False, "metaEvent": meta_event, "serverTimestamp": now.isoformat()}}, headers={"Access-Control-Allow-Origin": "null"})


@router.post("/api/public/promotion/channels/{slug}/pairing/start")
async def start_public_pairing(slug: str, request: Request, db: DbSession) -> JSONResponse:
    try:
        payload = PromotionPairingStart.model_validate_json(await request.body())
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_url=False)
        ) from None
    channel = _public_channel(db, slug, request)
    session_payload = _verify_session_token(channel, payload.session_token)
    traffic_source = session_payload.get("trafficSource", "direct")
    now = utcnow()
    from app.services.pairing_rate_limits import (
        PairingRateLimitRequest,
        PairingRateLimitUnavailable,
        consume_pairing_rate_limits,
        public_request_ip,
    )
    from app.services.protocol_nodes import channel_rate_limit_protocol

    preflight_protocol = channel_rate_limit_protocol(db, channel)
    source_ip = public_request_ip(request)
    preflight_limits = [
        PairingRateLimitRequest(
            "visitorCheck",
            f"channel:{channel.id}:visitor:{payload.visitor_id}",
        )
    ]
    if source_ip != "unknown":
        preflight_limits.append(
            PairingRateLimitRequest(
                "ipStart",
                f"channel:{channel.id}:ip:{source_ip}",
            )
        )
    try:
        preflight_decision = consume_pairing_rate_limits(
            preflight_protocol,
            preflight_limits,
        )
    except PairingRateLimitUnavailable:
        return _pairing_rate_limit_unavailable_response()
    limited = _pairing_rate_limit_response(preflight_decision)
    if limited is not None:
        return limited
    db.add(
        PromotionEvent(
            public_id=new_public_id("pevt"),
            channel_id=channel.id,
            event_type="pairing_check",
            idempotency_key=f"pairing_check:{uuid4().hex}",
            visitor_id=payload.visitor_id,
            occurred_at=now,
            country_code=channel.country_code,
            metadata_json={"trafficSource": traffic_source},
        )
    )
    # Persist the bounded lookup before checking whether the number exists, so
    # rejected numbers cannot be enumerated without consuming the same quota.
    db.commit()
    from app.services.protocol_nodes import (
        normalized_sync_policy,
        protocol_capacity,
        resolve_channel_ingress_protocol,
    )

    # A promotion channel belongs to one tenant. Landing-page accounts enter
    # that tenant's unified pool and retain the channel as their provenance.
    item = db.scalar(
        select(PersonalAccount)
        .where(
            PersonalAccount.phone_e164 == payload.phone,
            PersonalAccount.archived_at.is_(None),
        )
        .with_for_update()
    )
    if item is not None and item.created_by != channel.created_by:
        db.rollback()
        return _public_pairing_error(
            409,
            "number_unavailable",
            "该号码当前不能在这里绑定",
        )
    gateway_requires_reset = item is not None and item.status == "reauth_required"
    active_attempt = None
    if item is not None:
        active_attempt = db.scalar(
            select(AccountPairingAttempt)
            .where(
                AccountPairingAttempt.account_id == item.id,
                AccountPairingAttempt.status.in_(ACTIVE_PAIRING_STATUSES),
            )
            .order_by(AccountPairingAttempt.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if (
            active_attempt is not None
            and _utc_datetime(active_attempt.expires_at) <= now
        ):
            active_attempt.status = "expired"
            active_attempt.terminal_reason = "pairing_expired"
            if active_attempt.attempt_type == "initial":
                item.admission_status = "abandoned"
            active_attempt = None
        if active_attempt is not None and active_attempt.channel_id != channel.id:
            db.rollback()
            return _public_pairing_error(
                409,
                "pairing_in_progress",
                "该号码已有正在进行的绑定请求",
                retryable=True,
            )
        if (
            active_attempt is not None
            and active_attempt.visitor_id != payload.visitor_id
        ):
            db.rollback()
            return _public_pairing_error(
                409,
                "pairing_in_progress",
                "该号码已有正在进行的绑定请求",
                retryable=True,
            )

    is_reauthentication = (
        active_attempt is not None
        and active_attempt.attempt_type == "reauthentication"
    ) or (
        active_attempt is None
        and item is not None
        and item.admission_status == "active"
        and item.status in {"unpaired", "reauth_required"}
    )

    if active_attempt is not None:
        protocol = db.get(
            ProtocolNode,
            active_attempt.protocol_node_id or item.protocol_id,
        )
        if protocol is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="配对任务的协议节点不存在")
        if active_attempt.protocol_node_id is None:
            active_attempt.protocol_node_id = protocol.id
        if not active_attempt.sync_policy_json:
            active_attempt.sync_policy_version = protocol.sync_policy_version
            active_attempt.sync_policy_json = normalized_sync_policy(
                protocol.sync_policy_json
            )
    elif is_reauthentication:
        protocol = db.get(ProtocolNode, item.protocol_id)
        if (
            protocol is None
            or protocol.archived_at is not None
            or not protocol.online_enabled
        ):
            db.rollback()
            return _public_pairing_error(
                409,
                "protocol_unavailable",
                "该账号所属协议节点当前不可用",
                retryable=True,
            )
        capacity = protocol_capacity(db, protocol)
        if (
            protocol.max_concurrent_pairings is not None
            and capacity.active_pairings >= protocol.max_concurrent_pairings
        ):
            db.rollback()
            return _public_pairing_error(
                409,
                "protocol_capacity_limited",
                "该账号所属协议节点当前配对繁忙",
                retryable=True,
            )
    else:
        protocol = resolve_channel_ingress_protocol(db, channel)

    if active_attempt is None and not is_reauthentication:
        if channel.account_group_id is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="推广渠道尚未配置账号入库分组")
        landing_group = db.scalar(
            select(AccountGroup).where(
                AccountGroup.id == channel.account_group_id,
                AccountGroup.created_by == channel.created_by,
                AccountGroup.archived_at.is_(None),
            )
        )
        if landing_group is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="推广渠道的账号入库分组不可用")

    account_created = item is None
    if item is None:
        item = PersonalAccount(
            public_id=new_public_id("wa"),
            name=f"落地页账号 {payload.phone[-4:]}",
            phone_e164=payload.phone,
            country_code=channel.country_code,
            status="unpaired",
            source="landing_page",
            source_ref_type=(
                "promotion_channel_fission"
                if traffic_source == "fission"
                else "promotion_channel"
            ),
            source_ref_id=str(channel.id),
            validation_status="validating",
            metadata_sync_status="pending",
            admission_status="reserved",
            group_id=channel.account_group_id,
            protocol_id=protocol.id,
            enabled=True,
            marketing_eligible=channel.new_account_marketing_enabled,
            created_by=channel.created_by,
        )
        db.add(item)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="该号码已在账号池中") from None
    else:
        retryable_legacy_pairing = (
            item.source == "landing_page"
            and item.status == "linked_offline"
            and item.validation_status != "ready"
            and item.last_connected_at is None
        )
        retryable_initial = (
            item.admission_status in {"reserved", "abandoned"}
            and (
                item.status in {"unpaired", "pairing"}
                or retryable_legacy_pairing
            )
        )
        if active_attempt is None and not is_reauthentication and not retryable_initial:
            db.rollback()
            if item.validation_status == "ready" or item.status in {
                "linked_offline",
                "warming",
                "online_idle",
                "sending",
                "draining",
            }:
                return _public_pairing_error(
                    409,
                    "account_already_linked",
                    "该号码已经绑定并可用，无需重复绑定",
                )
            return _public_pairing_error(
                409,
                "number_unavailable",
                "该号码当前不能在这里绑定",
            )
        if retryable_legacy_pairing:
            # Releases before the verified-pairing state contract could leave
            # an interrupted landing-page attempt as linked_offline even
            # though it had never connected. Treat only that precise legacy
            # shape as retryable; imported or previously connected sessions
            # remain protected from replacement.
            item.status = "unpaired"
        item.validation_status = "validating"
        item.metadata_sync_status = "pending"
        if not is_reauthentication:
            item.admission_status = "reserved"
            item.source = "landing_page"
            item.source_ref_type = (
                "promotion_channel_fission"
                if traffic_source == "fission"
                else "promotion_channel"
            )
            item.source_ref_id = str(channel.id)
            item.group_id = channel.account_group_id
            item.protocol_id = protocol.id
            item.marketing_eligible = channel.new_account_marketing_enabled
    if active_attempt is not None:
        if (
            active_attempt.attempt_type == "initial"
            and active_attempt.account_group_id is None
        ):
            # A legacy in-flight attempt adopts the current channel default
            # once. Every subsequent request keeps that immutable snapshot.
            active_attempt.account_group_id = channel.account_group_id
        if active_attempt.attempt_type == "initial":
            item.group_id = active_attempt.account_group_id
            item.protocol_id = active_attempt.protocol_node_id or protocol.id
    if active_attempt is None:
        try:
            attempt_decision = consume_pairing_rate_limits(
                protocol,
                [
                    PairingRateLimitRequest(
                        "visitorAttempt",
                        f"channel:{channel.id}:visitor:{payload.visitor_id}",
                    ),
                    PairingRateLimitRequest(
                        "phoneAttempt",
                        f"tenant:{channel.created_by}:phone:{payload.phone}",
                        partition=f"tenant:{channel.created_by}",
                    ),
                    PairingRateLimitRequest(
                        "channelAttempt",
                        f"channel:{channel.id}",
                    ),
                ],
            )
        except PairingRateLimitUnavailable:
            db.rollback()
            return _pairing_rate_limit_unavailable_response()
        limited = _pairing_rate_limit_response(attempt_decision)
        if limited is not None:
            db.rollback()
            return limited

    from app.routers.personal_accounts import _auto_proxy, _proxy_url, _set_binding
    from app.services.wa_gateway import GatewayError, WaGatewayClient

    client = WaGatewayClient()
    try:
        if _proxy_url(db, item.gateway_account_id) is None:
            proxy = _auto_proxy(db, channel.created_by, channel.country_code)
            if proxy is None:
                db.rollback()
                raise HTTPException(status_code=409, detail="暂时没有可用的账号连接线路")
            _set_binding(db, item.gateway_account_id, entity_id(proxy))
        db.flush()
        if active_attempt is None:
            active_attempt = AccountPairingAttempt(
                public_id=new_public_id("pair"),
                attempt_type=(
                    "reauthentication" if is_reauthentication else "initial"
                ),
                account_id=item.id,
                channel_id=channel.id,
                account_group_id=item.group_id,
                protocol_node_id=protocol.id,
                route_version=channel.route_version,
                sync_policy_version=protocol.sync_policy_version,
                sync_policy_json=normalized_sync_policy(
                    protocol.sync_policy_json
                ),
                visitor_id=payload.visitor_id,
                status="code_issued",
                expires_at=now + timedelta(minutes=3),
            )
            db.add(active_attempt)
            db.flush()
        if account_created:
            from app.services.account_lifecycle import record_initial_account_state

            record_initial_account_state(
                db, item, reason_category="landing_page_pairing"
            )
        # The gateway emits account-state webhooks while pairing starts. Make
        # the account and its fixed proxy visible to that independent request
        # before calling the gateway, otherwise the webhook races an
        # uncommitted row and receives a false 404.
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该号码已在账号池中") from None

    try:
        try:
            client.create(
                item.gateway_account_id,
                payload.phone,
                _proxy_url(db, item.gateway_account_id),
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=active_attempt.sync_policy_json,
            )
        except GatewayError as exc:
            # An existing gateway account is normal when a visitor requests a
            # fresh code for an unpaired record; pairing remains authoritative.
            if "409" not in str(exc):
                raise
            client.update(
                item.gateway_account_id,
                connection_policy=protocol.connection_policy,
                idle_disconnect_seconds=protocol.idle_disconnect_seconds,
                post_verify_grace_seconds=protocol.post_verify_grace_seconds,
                sync_policy=active_attempt.sync_policy_json,
            )
        if (
            active_attempt.attempt_type == "reauthentication"
            and gateway_requires_reset
        ):
            result = client.reauthenticate(item.gateway_account_id, payload.phone)
        else:
            result = client.pair(
                item.gateway_account_id,
                payload.phone,
                "pairing_code",
                _proxy_url(db, item.gateway_account_id),
            )
        item.status = "linked_offline" if client.settings.wa_gateway_mock else "pairing"
        item.last_error = None
        try:
            expires_at = datetime.fromisoformat(
                str(result.get("expiresAt") or "").replace("Z", "+00:00")
            )
            expires_at = _utc_datetime(expires_at)
        except ValueError:
            expires_at = now + timedelta(minutes=3)
        if not now + timedelta(seconds=15) <= expires_at <= now + timedelta(minutes=10):
            expires_at = now + timedelta(minutes=3)
        active_attempt.status = "waiting_phone"
        active_attempt.expires_at = expires_at
        active_attempt.terminal_reason = None
        active_attempt.provider_code = None
        pairing_started_id = f"pairing_started:{active_attempt.id}"
        pairing_started_event = db.scalar(
            select(PromotionEvent).where(
                PromotionEvent.channel_id == channel.id,
                PromotionEvent.idempotency_key == pairing_started_id,
            )
        )
        if pairing_started_event is None:
            pairing_started_event = PromotionEvent(
                public_id=new_public_id("pevt"),
                channel_id=channel.id,
                event_type="pairing_started",
                idempotency_key=pairing_started_id,
                visitor_id=payload.visitor_id,
                occurred_at=now,
                country_code=channel.country_code,
                metadata_json={
                    "accountId": str(item.id),
                    "trafficSource": traffic_source,
                },
            )
            db.add(pairing_started_event)
            if active_attempt.attempt_type == "initial":
                from app.services.meta_conversions import enqueue_meta_conversion

                enqueue_meta_conversion(
                    db,
                    channel=channel,
                    event_key="pairing_started",
                    event_id=pairing_started_id,
                    event_time=now,
                    request=request,
                    phone=payload.phone,
                    visitor_id=payload.visitor_id,
                    custom_data={"trafficSource": traffic_source},
                )
        db.commit()
    except GatewayError as exc:
        db.rollback()
        failed = db.scalar(
            select(PersonalAccount).where(PersonalAccount.public_id == item.public_id)
        )
        if failed is not None:
            failed.status = "unpaired"
            failed.validation_status = "failed"
            failed.last_error = str(exc)[:2000]
            failed_attempt = db.scalar(
                select(AccountPairingAttempt)
                .where(
                    AccountPairingAttempt.account_id == failed.id,
                    AccountPairingAttempt.status.in_(ACTIVE_PAIRING_STATUSES),
                )
                .order_by(AccountPairingAttempt.created_at.desc())
                .limit(1)
            )
            if failed_attempt is not None:
                failed_attempt.status = "failed"
                failed_attempt.terminal_reason = "pairing_start_failed"
                if failed_attempt.attempt_type == "initial":
                    failed.admission_status = "abandoned"
            db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from None

    status_token = _pairing_status_token(
        channel, item, active_attempt, payload.visitor_id
    )
    from app.services.meta_conversions import browser_event_descriptor

    meta_event = (
        browser_event_descriptor(
            channel, "pairing_started", f"pairing_started:{active_attempt.id}"
        )
        if active_attempt.attempt_type == "initial"
        else None
    )
    return JSONResponse(
        {
            "data": {
                "pairing": {
                    "pairingCode": result.get("code"),
                    "attemptId": entity_id(active_attempt),
                    "pairingStatus": active_attempt.status,
                    "expiresAt": iso(active_attempt.expires_at),
                    "statusUrl": f"/api/public/promotion/channels/{slug}/pairing/{item.id}/status",
                    "cancelUrl": f"/api/public/promotion/channels/{slug}/pairing/{item.id}/cancel",
                    "statusToken": status_token,
                    "statusTokenHeader": "Authorization",
                    "statusTokenScheme": "Bearer",
                },
                "metaEvent": meta_event,
            }
        },
        headers={"Access-Control-Allow-Origin": "null"},
    )


@router.get(
    "/api/public/promotion/channels/{slug}/pairing/{account_id}/status"
)
def public_pairing_status(
    slug: str,
    account_id: str,
    request: Request,
    db: DbSession,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    channel = _public_channel(db, slug, request, require_active=False)
    try:
        database_id = parse_snowflake_id(account_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="账号链接不存在") from None
    item = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.id == database_id,
            PersonalAccount.created_by == channel.created_by,
            PersonalAccount.archived_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="账号链接不存在")
    attempt = db.scalar(
        select(AccountPairingAttempt)
        .where(
            AccountPairingAttempt.account_id == item.id,
            AccountPairingAttempt.channel_id == channel.id,
        )
        .order_by(AccountPairingAttempt.created_at.desc())
        .limit(1)
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="配对任务不存在")
    supplied_token = _pairing_bearer_token(authorization)
    token_payload = _verify_pairing_status_token(
        channel, item, attempt, supplied_token
    )
    from app.services.pairing_rate_limits import (
        PairingRateLimitRequest,
        PairingRateLimitUnavailable,
        consume_pairing_rate_limits,
    )

    protocol = db.get(
        ProtocolNode, attempt.protocol_node_id or item.protocol_id
    )
    if protocol is not None:
        try:
            status_decision = consume_pairing_rate_limits(
                protocol,
                [
                    PairingRateLimitRequest(
                        "status", f"attempt:{attempt.id}"
                    )
                ],
            )
        except PairingRateLimitUnavailable:
            return _pairing_rate_limit_unavailable_response()
        limited = _pairing_rate_limit_response(status_decision)
        if limited is not None:
            return limited
    from app.routers.personal_accounts import _apply_gateway_account
    from app.services.wa_gateway import GatewayError, WaGatewayClient

    client = WaGatewayClient()
    try:
        value = client.get(item.gateway_account_id)
        state = str(value.get("state") or item.status)
        gateway_pairing_status = str(value.get("pairingStatus") or "idle")
        _apply_gateway_account(item, value)
    except GatewayError:
        value = {}
        state = item.status
        gateway_pairing_status = attempt.status
    verified = (
        value.get("sessionStatus") == "verified"
        or state in {"online_idle", "sending"}
        or (client.settings.wa_gateway_mock and state == "linked_offline")
    )
    pairing_status = _public_pairing_status(
        state=state,
        gateway_pairing_status=gateway_pairing_status,
        verified=verified,
        attempt_status=attempt.status,
        expires_at=attempt.expires_at,
    )
    wakeup_group_id: int | None = None
    meta_event = None
    if pairing_status == "verified":
        newly_verified = attempt.status != "verified"
        became_dispatchable = (
            item.validation_status != "ready"
            or item.group_id != attempt.account_group_id
            or attempt.status != "verified"
        )
        item.status = state
        item.validation_status = "ready"
        item.admission_status = "active"
        if attempt.account_group_id is not None:
            item.group_id = attempt.account_group_id
        item.last_connected_at = item.last_connected_at or utcnow()
        attempt.status = "verified"
        attempt.verified_at = attempt.verified_at or utcnow()
        attempt.terminal_reason = None
        if attempt.attempt_type == "initial":
            success_event = db.scalar(
                select(PromotionEvent).where(
                    PromotionEvent.channel_id == channel.id,
                    PromotionEvent.idempotency_key == f"pair_success:{item.id}",
                )
            )
            if success_event is None:
                success_event = PromotionEvent(
                    public_id=new_public_id("pevt"),
                    channel_id=channel.id,
                    event_type="pair_success",
                    idempotency_key=f"pair_success:{item.id}",
                    visitor_id=str(token_payload.get("visitor") or "") or None,
                    occurred_at=utcnow(),
                    country_code=channel.country_code,
                    metadata_json={
                        "accountId": str(item.id),
                        "trafficSource": (
                            "fission"
                            if item.source_ref_type == "promotion_channel_fission"
                            else "direct"
                        ),
                    },
                )
                db.add(success_event)
                from app.services.meta_conversions import enqueue_meta_conversion

                enqueue_meta_conversion(
                    db,
                    channel=channel,
                    event_key="pairing_verified",
                    event_id=f"pairing_verified:{attempt.id}",
                    event_time=attempt.verified_at,
                    request=request,
                    phone=item.phone_e164,
                    visitor_id=str(token_payload.get("visitor") or "") or None,
                    custom_data={
                        "trafficSource": (
                            "fission"
                            if item.source_ref_type == "promotion_channel_fission"
                            else "direct"
                        )
                    },
                )
            from app.services.meta_conversions import browser_event_descriptor

            meta_event = browser_event_descriptor(
                channel, "pairing_verified", f"pairing_verified:{attempt.id}"
            )
        if newly_verified:
            from app.services.account_metadata_sync import (
                enqueue_account_metadata_sync,
            )

            enqueue_account_metadata_sync(
                db,
                item,
                sync_policy=attempt.sync_policy_json,
                sync_policy_version=attempt.sync_policy_version,
            )
        if became_dispatchable and item.group_id is not None:
            from app.services.account_group_wakeups import record_group_wakeup

            record_group_wakeup(
                db,
                item.group_id,
                reason="landing_page_account_verified",
                account_id=item.id,
            )
            wakeup_group_id = item.group_id
    elif pairing_status != attempt.status:
        attempt.status = pairing_status
        if pairing_status in {"expired", "cancelled", "failed"}:
            attempt.terminal_reason = str(
                value.get("reasonCategory")
                or ("pairing_expired" if pairing_status == "expired" else pairing_status)
            )[:64]
            provider_code = value.get("providerCode")
            attempt.provider_code = str(provider_code)[:64] if provider_code else None
            if attempt.attempt_type == "initial":
                item.admission_status = "abandoned"
                item.validation_status = "failed"
    db.commit()
    if wakeup_group_id is not None:
        from app.services.account_group_wakeups import (
            dispatch_group_wakeups_best_effort,
        )

        dispatch_group_wakeups_best_effort(wakeup_group_id)
    # `state` remains as a compatibility field for already-imported v1
    # templates, but now carries only the stable public pairing state. Raw
    # operational account state is diagnostic and must not drive template UI.
    legacy_state = {
        "verified": "ready",
        "failed": "failed",
        "expired": "expired",
        "cancelled": "failed",
        "code_issued": "pairing",
        "waiting_phone": "pairing",
        "reconnecting": "pairing",
    }[pairing_status]
    return JSONResponse(
        {
            "data": {
                "state": legacy_state,
                "accountState": state,
                "pairingStatus": pairing_status,
                "verified": pairing_status == "verified",
                "attemptId": entity_id(attempt),
                "expiresAt": iso(attempt.expires_at),
                "initializationStatus": item.metadata_sync_status,
                "reasonCode": attempt.terminal_reason,
                "providerCode": attempt.provider_code,
                "retryable": pairing_status in {"expired", "cancelled", "failed"},
                "nextPollAfterMs": 3000 if pairing_status == "reconnecting" else 2000,
                "metaEvent": meta_event,
            }
        },
        headers={"Access-Control-Allow-Origin": "null"},
    )


@router.post(
    "/api/public/promotion/channels/{slug}/pairing/{account_id}/cancel"
)
def cancel_public_pairing(
    slug: str,
    account_id: str,
    request: Request,
    db: DbSession,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    channel = _public_channel(db, slug, request, require_active=False)
    try:
        database_id = parse_snowflake_id(account_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="账号链接不存在") from None
    item = db.scalar(
        select(PersonalAccount).where(
            PersonalAccount.id == database_id,
            PersonalAccount.created_by == channel.created_by,
            PersonalAccount.archived_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="账号链接不存在")
    attempt = db.scalar(
        select(AccountPairingAttempt)
        .where(
            AccountPairingAttempt.account_id == item.id,
            AccountPairingAttempt.channel_id == channel.id,
        )
        .order_by(AccountPairingAttempt.created_at.desc())
        .limit(1)
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="配对任务不存在")
    _verify_pairing_status_token(
        channel, item, attempt, _pairing_bearer_token(authorization)
    )
    from app.services.pairing_rate_limits import (
        PairingRateLimitRequest,
        PairingRateLimitUnavailable,
        consume_pairing_rate_limits,
    )

    protocol = db.get(
        ProtocolNode, attempt.protocol_node_id or item.protocol_id
    )
    if protocol is not None:
        try:
            cancel_decision = consume_pairing_rate_limits(
                protocol,
                [
                    PairingRateLimitRequest(
                        "cancel", f"attempt:{attempt.id}"
                    )
                ],
            )
        except PairingRateLimitUnavailable:
            return _pairing_rate_limit_unavailable_response()
        limited = _pairing_rate_limit_response(cancel_decision)
        if limited is not None:
            return limited
    if attempt.status in ACTIVE_PAIRING_STATUSES:
        from app.services.wa_gateway import GatewayError, WaGatewayClient

        try:
            WaGatewayClient().cancel_pairing(item.gateway_account_id)
        except GatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        attempt.status = "cancelled"
        attempt.terminal_reason = "pairing_cancelled"
        item.status = "unpaired"
        item.validation_status = "failed"
        item.last_error = "配对已取消"
        if attempt.attempt_type == "initial":
            item.admission_status = "abandoned"
        db.commit()
    return JSONResponse(
        {"data": {"pairingStatus": attempt.status, "cancelled": True}},
        headers={"Access-Control-Allow-Origin": "null"},
    )


@router.post("/api/internal/promotion/success-events")
async def report_internal_success(request: Request, db: DbSession) -> JSONResponse:
    raw = await request.body()
    secret = get_settings().promotion_success_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="推广成功事件密钥未配置")
    supplied = request.headers.get("X-Parloq-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, f"sha256={expected}"):
        raise HTTPException(status_code=401, detail="推广成功事件签名无效")
    try:
        payload = PromotionSuccessInput.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from None
    channel = db.scalar(
        select(PromotionChannel).where(
            identifier_filter(PromotionChannel, payload.promotion_channel_id),
            PromotionChannel.archived_at.is_(None),
        )
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="推广渠道不存在")
    existing = db.scalar(
        select(PromotionEvent).where(
            PromotionEvent.channel_id == channel.id,
            PromotionEvent.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return JSONResponse({"data": {"ok": True, "duplicate": True}})
    occurred_at = parse_public_datetime(payload.occurred_at)
    now = utcnow()
    if occurred_at < now - timedelta(days=30) or occurred_at > now + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="成功事件时间超出允许窗口")
    db.add(
        PromotionEvent(
            public_id=new_public_id("pevt"),
            channel_id=channel.id,
            event_type=payload.event_type,
            idempotency_key=payload.idempotency_key,
            visitor_id=payload.visitor_id,
            occurred_at=occurred_at,
            country_code=channel.country_code,
            metadata_json=payload.metadata,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse({"data": {"ok": True, "duplicate": True}})
    return JSONResponse({"data": {"ok": True, "duplicate": False}})


@router.get("/api/promotion/channels/{channel_id}/leads")
def list_leads(channel_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    channel = _channel(db, channel_id, current_user); items = db.scalars(select(PromotionLead).where(PromotionLead.channel_id == channel.id).order_by(PromotionLead.last_seen_at.desc())).all(); rows = [{"id": entity_id(x), "phone": x.phone_e164, "countryCode": x.country_code, "firstSeenAt": iso(x.first_seen_at), "lastSeenAt": iso(x.last_seen_at), "submissionCount": x.submission_count} for x in items]; return {"data": {"rows": rows, "total": len(rows)}}


@router.get("/api/promotion/channels/{channel_id}/stats")
def channel_stats(channel_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    channel = _channel(db, channel_id, current_user); events = db.scalars(select(PromotionEvent).where(PromotionEvent.channel_id == channel.id)).all(); totals = {name: 0 for name in ("page_view", "phone_submit", "visit_end", "login_success", "pair_success")}; daily: dict[str, dict] = {}
    for event in events:
        totals[event.event_type] = totals.get(event.event_type, 0) + 1; key = event.occurred_at.date().isoformat(); daily.setdefault(key, {"date": key, "pageView": 0, "phoneSubmit": 0, "visitEnd": 0, "loginSuccess": 0, "pairSuccess": 0}); field = {"page_view":"pageView","phone_submit":"phoneSubmit","visit_end":"visitEnd","login_success":"loginSuccess","pair_success":"pairSuccess"}.get(event.event_type)
        if field: daily[key][field] += 1
    visitors = {event.visitor_id or f"legacy:{event.id}" for event in events if event.event_type == "page_view"}
    return {"data": {"totals": {"pageView": totals["page_view"], "uv": len(visitors), "phoneSubmit": totals["phone_submit"], "visitEnd": totals["visit_end"], "loginSuccess": totals["login_success"], "pairSuccess": totals["pair_success"], "successes": totals["login_success"] + totals["pair_success"], "uniqueLeads": int(db.scalar(select(func.count()).select_from(PromotionLead).where(PromotionLead.channel_id == channel.id)) or 0)}, "series": sorted(daily.values(), key=lambda x: x["date"])}}


def _ad_metric_row(db: DbSession, item: AdMetric) -> dict:
    channel = db.get(PromotionChannel, item.promotion_channel_id)
    return {
        "id": entity_id(item),
        "date": item.metric_date.isoformat(),
        "promotionChannelId": entity_id(channel) if channel else None,
        "promotionChannelName": channel.name if channel else None,
        "channel": item.channel,
        "countryCode": item.country_code,
        "spend": float(item.spend),
        "adFeeRate": float(item.ad_fee_rate),
        "feeAmount": round(
            float(item.spend) * float(item.ad_fee_rate) / 100, 6
        ),
        "totalCost": round(
            float(item.spend) * (1 + float(item.ad_fee_rate) / 100)
            + float(item.other_cost),
            6,
        ),
        "otherCost": float(item.other_cost),
        "impressions": item.impressions,
        "clicks": item.clicks,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def _metric_channel(db: DbSession, channel_id: str, user) -> PromotionChannel:
    return _channel(db, channel_id, user)


def _apply_metric(db: DbSession, payload, user, current: AdMetric | None = None) -> AdMetric:
    channel = (
        _metric_channel(db, payload.promotion_channel_id, user)
        if getattr(payload, "promotion_channel_id", None)
        else db.get(PromotionChannel, current.promotion_channel_id)
    )
    item = current or AdMetric(
        public_id=new_public_id("ad"),
        metric_date=payload.metric_date,
        promotion_channel_id=channel.id,
        channel=channel.channel_type,
        country_code=channel.country_code,
        spend=payload.spend,
        ad_fee_rate=payload.ad_fee_rate,
        other_cost=payload.other_cost,
        impressions=payload.impressions,
        clicks=payload.clicks,
    )
    if current:
        if payload.metric_date is not None:
            item.metric_date = payload.metric_date
        if payload.promotion_channel_id is not None:
            item.promotion_channel_id = channel.id
            item.channel = channel.channel_type
            item.country_code = channel.country_code
        for field in (
            "spend",
            "ad_fee_rate",
            "other_cost",
            "impressions",
            "clicks",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(item, field, value)
    db.add(item)
    return item


def _metric_statement(
    db: DbSession,
    user,
    date_from: date | None,
    date_to: date | None,
    promotion_channel_id: str | None,
):
    statement = select(AdMetric).join(PromotionChannel)
    if user.role != "admin":
        statement = statement.where(PromotionChannel.created_by == user.id)
    if date_from:
        statement = statement.where(AdMetric.metric_date >= date_from)
    if date_to:
        statement = statement.where(AdMetric.metric_date <= date_to)
    if promotion_channel_id:
        channel = _metric_channel(db, promotion_channel_id, user)
        statement = statement.where(AdMetric.promotion_channel_id == channel.id)
    return statement


@router.get("/api/promotion/ad-metrics")
def list_ad_metrics(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    promotion_channel_id: str | None = Query(default=None, alias="promotionChannelId"),
) -> dict:
    items = db.scalars(
        _metric_statement(db, current_user, date_from, date_to, promotion_channel_id).order_by(
            AdMetric.metric_date.desc(), AdMetric.id.desc()
        )
    ).all()
    return {"data": {"rows": [_ad_metric_row(db, item) for item in items], "total": len(items)}}


@router.post("/api/promotion/ad-metrics", status_code=201)
def create_ad_metric(payload: AdMetricInput, db: DbSession, current_user: CurrentUser) -> dict:
    item = _apply_metric(db, payload, current_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该推广渠道日期的数据已存在") from None
    return {"data": {"adMetric": _ad_metric_row(db, item)}}


@router.patch("/api/promotion/ad-metrics/{ad_metric_id}")
def update_ad_metric(
    ad_metric_id: str, payload: AdMetricUpdate, db: DbSession, current_user: CurrentUser
) -> dict:
    statement = select(AdMetric).join(PromotionChannel).where(
        identifier_filter(AdMetric, ad_metric_id)
    )
    if current_user.role != "admin": statement = statement.where(PromotionChannel.created_by == current_user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="广告日数据不存在")
    _apply_metric(db, payload, current_user, item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该推广渠道日期的数据已存在") from None
    return {"data": {"adMetric": _ad_metric_row(db, item)}}


@router.delete("/api/promotion/ad-metrics/{ad_metric_id}")
def delete_ad_metric(ad_metric_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    statement = select(AdMetric).join(PromotionChannel).where(
        identifier_filter(AdMetric, ad_metric_id)
    )
    if current_user.role != "admin": statement = statement.where(PromotionChannel.created_by == current_user.id)
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="广告日数据不存在")
    db.delete(item)
    db.commit()
    return {"data": {"ok": True}}


@router.post("/api/promotion/ad-metrics/import")
def import_ad_metrics(payload: AdMetricImport, db: DbSession, current_user: CurrentUser) -> dict:
    created = 0
    for row in payload.rows:
        channel = _metric_channel(db, row.promotion_channel_id, current_user)
        item = db.scalar(
            select(AdMetric).where(
                AdMetric.metric_date == row.metric_date,
                AdMetric.promotion_channel_id == channel.id,
            )
        )
        if item:
            item.spend = row.spend
            item.ad_fee_rate = row.ad_fee_rate
            item.other_cost = row.other_cost
            item.impressions = row.impressions
            item.clicks = row.clicks
            item.channel = channel.channel_type
            item.country_code = channel.country_code
        else:
            _apply_metric(db, row, current_user)
            created += 1
    db.commit()
    return {"data": {"importedCount": created, "processedCount": len(payload.rows)}}


def _ratio(numerator, denominator, multiplier: int = 1) -> float:
    return round(float(numerator) * multiplier / float(denominator), 6) if denominator else 0.0


def _rate(numerator, denominator) -> float:
    return min(1.0, _ratio(numerator, denominator))


def _nullable_ratio(numerator, denominator) -> float | None:
    return _ratio(numerator, denominator) if denominator else None


def _nullable_rate(numerator, denominator) -> float | None:
    value = _nullable_ratio(numerator, denominator)
    return min(1.0, value) if value is not None else None


@router.get("/api/promotion/ad-metrics/summary")
def ad_metric_summary(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    promotion_channel_id: str | None = Query(default=None, alias="promotionChannelId"),
) -> dict:
    analytics = _analytics_data(
        db,
        current_user,
        date_from,
        date_to,
        promotion_channel_id,
        None,
        None,
        None,
    )
    summary = analytics["summary"]
    return {
        "data": {
            **summary,
            "cpm": _ratio(summary["spend"], summary["impressions"], 1000),
            "cpc": _ratio(summary["spend"], summary["clicks"]),
            "deprecated": True,
            "replacement": "/api/promotion/data-center/channels",
        }
    }


def _csv_values(raw: str | None) -> set[str]:
    return {value.strip() for value in (raw or "").split(",") if value.strip()}


def _analytics_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    # Reporting dates follow the deployment's business timezone rather than
    # UTC midnight, matching the date users enter for advertising metrics.
    end = date_to or datetime.now(REPORT_TIMEZONE).date()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="dateFrom 不能晚于 dateTo")
    if (end - start).days > 365:
        raise HTTPException(status_code=422, detail="数据中心单次最多查询 366 天")
    return start, end


def _empty_analytics_bucket() -> dict:
    return {
        "spend": Decimal("0"),
        "feeAmount": Decimal("0"),
        "otherCost": Decimal("0"),
        "impressions": 0,
        "clicks": 0,
        "pageViews": 0,
        "submissions": 0,
        "loginSuccess": 0,
        "pairSuccess": 0,
        "_visitors": set(),
        "_uniqueLeads": set(),
        "_successfulVisitors": set(),
        "fissionPageViews": 0,
        "fissionSubmissions": 0,
        "fissionLoginSuccess": 0,
        "fissionPairSuccess": 0,
        "_fissionVisitors": set(),
        "_fissionUniqueLeads": set(),
        "_fissionSuccessfulVisitors": set(),
        "_adMetricId": None,
    }


def _merge_analytics_bucket(target: dict, source: dict) -> None:
    for field in (
        "spend",
        "feeAmount",
        "otherCost",
        "impressions",
        "clicks",
        "pageViews",
        "submissions",
        "loginSuccess",
        "pairSuccess",
        "fissionPageViews",
        "fissionSubmissions",
        "fissionLoginSuccess",
        "fissionPairSuccess",
    ):
        target[field] += source[field]
    target["_visitors"].update(source["_visitors"])
    target["_uniqueLeads"].update(source["_uniqueLeads"])
    target["_successfulVisitors"].update(source["_successfulVisitors"])
    target["_fissionVisitors"].update(source["_fissionVisitors"])
    target["_fissionUniqueLeads"].update(source["_fissionUniqueLeads"])
    target["_fissionSuccessfulVisitors"].update(
        source["_fissionSuccessfulVisitors"]
    )


def _finalize_analytics(bucket: dict) -> dict:
    spend = Decimal(bucket["spend"])
    fee_amount = Decimal(bucket["feeAmount"])
    other_cost = Decimal(bucket["otherCost"])
    total_cost = spend + fee_amount + other_cost
    uv = len(bucket["_visitors"])
    unique_leads = len(bucket["_uniqueLeads"])
    successes = len(bucket["_successfulVisitors"])
    impressions = int(bucket["impressions"])
    clicks = int(bucket["clicks"])
    login_requests = int(bucket["submissions"])
    login_request_uv = len(bucket["_uniqueLeads"])
    login_success_attempts = int(bucket["loginSuccess"]) + int(
        bucket["pairSuccess"]
    )
    fission_uv = len(bucket["_fissionVisitors"])
    fission_request_uv = len(bucket["_fissionUniqueLeads"])
    fission_success_uv = len(bucket["_fissionSuccessfulVisitors"])
    fission_success_attempts = int(bucket["fissionLoginSuccess"]) + int(
        bucket["fissionPairSuccess"]
    )
    return {
        "spend": float(spend),
        "feeAmount": float(fee_amount),
        "otherCost": float(other_cost),
        "totalCost": float(total_cost),
        "impressions": impressions,
        "clicks": clicks,
        "pageViews": int(bucket["pageViews"]),
        "uv": uv,
        "submissions": login_requests,
        "uniqueLeads": login_request_uv,
        "leads": login_request_uv,
        "loginRequest": login_requests,
        "loginRequestUv": login_request_uv,
        "loginSuccess": int(bucket["loginSuccess"]),
        "pairSuccess": int(bucket["pairSuccess"]),
        "loginSuccessCount": login_success_attempts,
        "loginSuccessUv": successes,
        "successes": successes,
        "ctr": _nullable_rate(clicks, impressions),
        "requestRate": _nullable_rate(login_request_uv, uv),
        "successRate": _nullable_rate(successes, login_request_uv),
        "visitorSuccessRate": _nullable_rate(successes, uv),
        "costPerLead": _nullable_ratio(spend, login_request_uv),
        "costPerSuccess": _nullable_ratio(spend, successes),
        "fissionPageViews": int(bucket["fissionPageViews"]),
        "fissionUv": fission_uv,
        "fissionLoginRequest": int(bucket["fissionSubmissions"]),
        "fissionLoginRequestUv": fission_request_uv,
        "fissionLoginSuccessCount": fission_success_attempts,
        "fissionLoginSuccessUv": fission_success_uv,
        "fissionRequestRate": _nullable_rate(fission_request_uv, fission_uv),
        "fissionSuccessRate": _nullable_rate(
            fission_success_uv, fission_request_uv
        ),
        "fissionVisitorSuccessRate": _nullable_rate(fission_success_uv, fission_uv),
    }


def _analytics_data(
    db: DbSession,
    user,
    date_from: date | None,
    date_to: date | None,
    channel_ids_raw: str | None,
    template_ids_raw: str | None,
    country_codes_raw: str | None,
    creator_ids_raw: str | None,
) -> dict:
    start, end = _analytics_range(date_from, date_to)
    channel_ids = _csv_values(channel_ids_raw)
    template_ids = _csv_values(template_ids_raw)
    country_codes = {value.upper() for value in _csv_values(country_codes_raw)}
    try:
        creator_ids = {
            parse_snowflake_id(value) for value in _csv_values(creator_ids_raw)
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="creatorIds 格式不正确") from exc
    if user.role != "admin" and creator_ids and creator_ids != {user.id}:
        raise HTTPException(status_code=403, detail="不能查询其他用户的数据")

    statement = select(PromotionChannel).where(PromotionChannel.archived_at.is_(None))
    if user.role != "admin":
        statement = statement.where(PromotionChannel.created_by == user.id)
    if channel_ids:
        statement = statement.where(identifiers_filter(PromotionChannel, channel_ids))
    if country_codes:
        statement = statement.where(PromotionChannel.country_code.in_(country_codes))
    if creator_ids:
        statement = statement.where(PromotionChannel.created_by.in_(creator_ids))
    channels = list(db.scalars(statement.order_by(PromotionChannel.created_at.desc())).all())
    if template_ids:
        allowed_templates = set(
            db.scalars(
                select(PromotionTemplate.id).where(
                    identifiers_filter(PromotionTemplate, template_ids)
                )
            ).all()
        )
        channels = [channel for channel in channels if channel.template_id in allowed_templates]
    channel_pks = [channel.id for channel in channels]

    daily: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        daily[cursor.isoformat()] = _empty_analytics_bucket()
        cursor += timedelta(days=1)
    grouped: dict[tuple[int, str], dict] = {
        (channel.id, channel.country_code): _empty_analytics_bucket() for channel in channels
    }
    grouped_daily: dict[tuple[int, str], dict[str, dict]] = {}
    channel_map = {channel.id: channel for channel in channels}

    if channel_pks:
        metrics = db.scalars(
            select(AdMetric).where(
                AdMetric.promotion_channel_id.in_(channel_pks),
                AdMetric.metric_date >= start,
                AdMetric.metric_date <= end,
            )
        ).all()
        event_start = datetime.combine(
            start, time.min, tzinfo=REPORT_TIMEZONE
        ).astimezone(UTC)
        event_end = datetime.combine(
            end + timedelta(days=1), time.min, tzinfo=REPORT_TIMEZONE
        ).astimezone(UTC)
        events = db.scalars(
            select(PromotionEvent).where(
                PromotionEvent.channel_id.in_(channel_pks),
                PromotionEvent.occurred_at >= event_start,
                PromotionEvent.occurred_at < event_end,
            )
        ).all()
    else:
        metrics = []
        events = []

    for metric in metrics:
        date_key = metric.metric_date.isoformat()
        group_key = (
            metric.promotion_channel_id,
            channel_map[metric.promotion_channel_id].country_code,
        )
        group = grouped.setdefault(group_key, _empty_analytics_bucket())
        detail = grouped_daily.setdefault(group_key, {}).setdefault(
            date_key, _empty_analytics_bucket()
        )
        detail["_adMetricId"] = entity_id(metric)
        for target in (daily[date_key], group, detail):
            target["spend"] += Decimal(metric.spend)
            target["feeAmount"] += Decimal(metric.spend) * Decimal(
                metric.ad_fee_rate
            ) / Decimal("100")
            target["otherCost"] += Decimal(metric.other_cost)
            target["impressions"] += metric.impressions
            target["clicks"] += metric.clicks

    for event in events:
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        date_key = occurred_at.astimezone(REPORT_TIMEZONE).date().isoformat()
        country_code = channel_map[event.channel_id].country_code
        group_key = (event.channel_id, country_code)
        group = grouped.setdefault(group_key, _empty_analytics_bucket())
        detail = grouped_daily.setdefault(group_key, {}).setdefault(
            date_key, _empty_analytics_bucket()
        )
        is_fission = (
            isinstance(event.metadata_json, dict)
            and event.metadata_json.get("trafficSource") == "fission"
        )
        for target in (daily[date_key], group, detail):
            visitor_key = (
                event.channel_id,
                event.visitor_id or f"legacy:{event.id}",
            )
            lead_key = (
                event.channel_id,
                event.lead_id
                if event.lead_id is not None
                else f"legacy-event:{event.id}",
            )
            if is_fission:
                if event.event_type == "page_view":
                    target["fissionPageViews"] += 1
                    target["_fissionVisitors"].add(visitor_key)
                elif event.event_type == "phone_submit":
                    target["fissionSubmissions"] += 1
                    target["_fissionUniqueLeads"].add(lead_key)
                elif event.event_type == "login_success":
                    target["fissionLoginSuccess"] += 1
                    target["_fissionSuccessfulVisitors"].add(visitor_key)
                elif event.event_type == "pair_success":
                    target["fissionPairSuccess"] += 1
                    target["_fissionSuccessfulVisitors"].add(visitor_key)
            elif event.event_type == "page_view":
                target["pageViews"] += 1
                target["_visitors"].add(visitor_key)
            elif event.event_type == "phone_submit":
                target["submissions"] += 1
                target["_uniqueLeads"].add(lead_key)
            elif event.event_type == "login_success":
                target["loginSuccess"] += 1
                target["_successfulVisitors"].add(visitor_key)
            elif event.event_type == "pair_success":
                target["pairSuccess"] += 1
                target["_successfulVisitors"].add(visitor_key)

    total = _empty_analytics_bucket()
    for bucket in daily.values():
        _merge_analytics_bucket(total, bucket)

    rows = []
    for (channel_pk, country_code), bucket in grouped.items():
        channel = channel_map[channel_pk]
        template = db.get(PromotionTemplate, channel.template_id)
        creator = db.get(UserAccount, channel.created_by)
        detail_map = grouped_daily.get((channel_pk, country_code), {})
        detail_rows = []
        for value in sorted(daily):
            detail_bucket = detail_map.get(value, _empty_analytics_bucket())
            detail_rows.append(
                {
                    "date": value,
                    "adMetricId": detail_bucket["_adMetricId"],
                    **_finalize_analytics(detail_bucket),
                }
            )
        rows.append(
            {
                "promotionChannelId": entity_id(channel),
                "promotionChannelName": channel.name,
                "channelType": channel.channel_type,
                "countryCode": country_code,
                "templateId": entity_id(template) if template else None,
                "templateName": template.name if template else None,
                "creatorId": str(channel.created_by),
                "creatorName": creator.display_name or creator.username if creator else None,
                **_finalize_analytics(bucket),
                "daily": detail_rows,
            }
        )
    rows.sort(key=lambda row: (row["successes"], row["leads"], row["uv"]), reverse=True)
    return {
        "range": {"dateFrom": start.isoformat(), "dateTo": end.isoformat()},
        "summary": _finalize_analytics(total),
        "series": [
            {"date": value, **_finalize_analytics(bucket)}
            for value, bucket in sorted(daily.items())
        ],
        "rows": rows,
        "definitions": {
            "uv": "按 (channel, visitorId) 去重；历史无 visitorId 的浏览事件按单次访问计数",
            "submissions": "phone_submit 原始提交事件数",
            "uniqueLeads": "窗口内 phone_submit 按 (channel, lead) 去重的获号数",
            "successes": "HMAC 内部成功事件按 (channel, visitorId) 终态去重",
            "requestRate": "uniqueLeads / uv，最大为 100%",
            "successRate": "successes / uniqueLeads，最大为 100%",
            "visitorSuccessRate": "successes / uv",
            "costPerSuccess": "广告消耗 spend / 登录成功人数；手续费与其他费用仅计入总成本",
            "fission": "trafficSource=fission 的裂变访问单独聚合，不混入直推漏斗",
        },
    }


@router.get("/api/promotion/data-center/overview")
def promotion_data_center_overview(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    channel_ids: str | None = Query(default=None, alias="channelIds"),
    template_ids: str | None = Query(default=None, alias="templateIds"),
    country_codes: str | None = Query(default=None, alias="countryCodes"),
    creator_ids: str | None = Query(default=None, alias="creatorIds"),
) -> dict:
    data = _analytics_data(db, current_user, date_from, date_to, channel_ids, template_ids, country_codes, creator_ids)
    return {"data": {"range": data["range"], "summary": data["summary"], "definitions": data["definitions"]}}


@router.get("/api/promotion/data-center/trends")
def promotion_data_center_trends(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    channel_ids: str | None = Query(default=None, alias="channelIds"),
    template_ids: str | None = Query(default=None, alias="templateIds"),
    country_codes: str | None = Query(default=None, alias="countryCodes"),
    creator_ids: str | None = Query(default=None, alias="creatorIds"),
) -> dict:
    data = _analytics_data(db, current_user, date_from, date_to, channel_ids, template_ids, country_codes, creator_ids)
    return {"data": {"range": data["range"], "summary": data["summary"], "series": data["series"], "definitions": data["definitions"]}}


@router.get("/api/promotion/data-center/channels")
def promotion_data_center_channels(
    db: DbSession,
    current_user: CurrentUser,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    channel_ids: str | None = Query(default=None, alias="channelIds"),
    template_ids: str | None = Query(default=None, alias="templateIds"),
    country_codes: str | None = Query(default=None, alias="countryCodes"),
    creator_ids: str | None = Query(default=None, alias="creatorIds"),
) -> dict:
    data = _analytics_data(db, current_user, date_from, date_to, channel_ids, template_ids, country_codes, creator_ids)
    return {"data": {"range": data["range"], "summary": data["summary"], "rows": data["rows"], "total": len(data["rows"]), "definitions": data["definitions"]}}
