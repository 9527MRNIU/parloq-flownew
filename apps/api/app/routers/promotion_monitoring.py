from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import BigInteger, String, case, cast, func, literal, or_, select, union_all

from app.deps import CurrentUser, DbSession
from app.entity_ids import entity_id, identifier_filter
from app.models import (
    DomainRecord,
    PromotionChannel,
    PromotionEvent,
    PromotionIntegration,
    PromotionIntegrationEvent,
    PromotionTemplate,
    PromotionVisitor,
)
from app.serializers import iso


router = APIRouter(prefix="/api/promotion/monitoring", tags=["promotion-monitoring"])

CLIENT_EVENT_TYPES = {"page_view", "visit_end", "inspection_detected"}
EVENT_LABELS = {
    "page_view": "页面访问",
    "phone_submit": "提交号码",
    "visit_end": "离开页面",
    "inspection_detected": "页面保护触发",
    "pairing_check": "配对检查",
    "pairing_started": "生成配对码",
    "pairing_failed": "配对失败",
    "login_success": "登录成功",
    "pair_success": "账号接入成功",
}
SOURCE_LABELS = {
    "client": "客户端行为",
    "server": "服务端业务",
    "integration": "集成回传",
}

BROWSER_SIGNATURES = (
    (
        "Instagram 内置浏览器",
        re.compile(r"Instagram(?:/|\s)([0-9.]+)", re.IGNORECASE),
    ),
    (
        "Facebook 内置浏览器",
        re.compile(r"FBAV/([0-9.]+)", re.IGNORECASE),
    ),
    ("Chrome iOS", re.compile(r"CriOS/([0-9.]+)", re.IGNORECASE)),
    ("Firefox iOS", re.compile(r"FxiOS/([0-9.]+)", re.IGNORECASE)),
    ("Edge iOS", re.compile(r"EdgiOS/([0-9.]+)", re.IGNORECASE)),
    ("Edge", re.compile(r"EdgA?/([0-9.]+)", re.IGNORECASE)),
    ("Opera", re.compile(r"(?:OPR|Opera)/([0-9.]+)", re.IGNORECASE)),
    ("Samsung Internet", re.compile(r"SamsungBrowser/([0-9.]+)", re.IGNORECASE)),
    ("Chrome", re.compile(r"(?:Chrome|Chromium)/([0-9.]+)", re.IGNORECASE)),
    ("Firefox", re.compile(r"Firefox/([0-9.]+)", re.IGNORECASE)),
    ("Safari", re.compile(r"Version/([0-9.]+).*Safari/", re.IGNORECASE)),
)
IOS_VERSION = re.compile(
    r"(?:CPU (?:iPhone )?OS|iPhone OS) ([0-9_]+)", re.IGNORECASE
)
ANDROID_VERSION = re.compile(r"Android[ /]([0-9.]+)", re.IGNORECASE)
WINDOWS_VERSION = re.compile(r"Windows NT ([0-9.]+)", re.IGNORECASE)
MACOS_VERSION = re.compile(r"Mac OS X[ /]([0-9_]+)", re.IGNORECASE)
WINDOWS_VERSION_LABELS = {
    "10.0": "10 / 11",
    "6.3": "8.1",
    "6.2": "8",
    "6.1": "7",
}


def _range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    end_date = date_to or datetime.now(UTC).date()
    start_date = date_from or end_date - timedelta(days=6)
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
    if (end_date - start_date).days > 89:
        raise HTTPException(status_code=422, detail="访问监控单次最多查询 90 天")
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC),
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC),
    )


def _visible_channel_ids(db: DbSession, user) -> list[int]:
    statement = select(PromotionChannel.id)
    if user.role != "admin":
        statement = statement.where(PromotionChannel.created_by == user.id)
    return list(db.scalars(statement).all())


def _hostname(channel: PromotionChannel, domain: DomainRecord | None) -> str:
    if domain is None:
        return ""
    prefix = (channel.subdomain_prefix or "").strip()
    return f"{prefix}.{domain.hostname}" if prefix else domain.hostname


def _landing(channel: PromotionChannel, domain: DomainRecord | None) -> dict[str, Any]:
    hostname = _hostname(channel, domain)
    return {
        "hostname": hostname or None,
        "url": (
            f"https://{hostname}/{channel.slug}"
            if hostname
            else f"/api/public/promotion/channels/{channel.slug}/render"
        ),
    }


def _normalized_viewport(value: Any) -> list[int] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return [int(value[0]), int(value[1])]
    except (TypeError, ValueError):
        return None


def _device_type(user_agent: str | None) -> str:
    value = user_agent or ""
    if "iPad" in value or "Tablet" in value:
        return "tablet"
    if "Mobile" in value or "iPhone" in value or "Android" in value:
        return "mobile"
    return "desktop"


def _device_summary(metadata: dict | None) -> dict[str, Any]:
    request_context = (metadata or {}).get("requestContext")
    client_context = (metadata or {}).get("clientContext")
    if not isinstance(request_context, dict):
        request_context = {}
    if not isinstance(client_context, dict):
        client_context = {}
    user_agent = str(request_context.get("userAgent") or "")
    browser = "未知浏览器"
    browser_version = None
    for browser_name, signature in BROWSER_SIGNATURES:
        match = signature.search(user_agent)
        if match:
            browser = browser_name
            browser_version = match.group(1)
            break

    system_version = None
    if "iPhone" in user_agent or "iPad" in user_agent:
        system = "iOS"
        match = IOS_VERSION.search(user_agent)
        system_version = match.group(1).replace("_", ".") if match else None
    elif "Android" in user_agent:
        system = "Android"
        match = ANDROID_VERSION.search(user_agent)
        system_version = match.group(1) if match else None
    elif "Windows" in user_agent:
        system = "Windows"
        match = WINDOWS_VERSION.search(user_agent)
        if match:
            system_version = WINDOWS_VERSION_LABELS.get(match.group(1), match.group(1))
    elif "Macintosh" in user_agent or "Mac OS" in user_agent:
        system = "macOS"
        match = MACOS_VERSION.search(user_agent)
        system_version = match.group(1).replace("_", ".") if match else None
    elif "Linux" in user_agent:
        system = "Linux"
    else:
        system = "未知系统"
    return {
        "type": _device_type(user_agent),
        "browser": browser,
        "browserVersion": browser_version,
        "system": system,
        "systemVersion": system_version,
        "viewport": _normalized_viewport(client_context.get("viewport")),
        "userAgent": user_agent or None,
    }


def _json_text(column, *path: str):
    value = column
    for key in path:
        value = value[key]
    return value.as_string()


def _json_value(column, *path: str):
    value = column
    for key in path:
        value = value[key]
    return value


def _monitoring_sources(channel_ids: list[int], start: datetime, end: datetime):
    landing_metadata = PromotionEvent.metadata_json
    landing_request_context = PromotionEvent.request_context_json
    integration_metadata = PromotionIntegrationEvent.metadata_json
    integration_request_context = PromotionIntegrationEvent.request_context_json
    landing = select(
        literal("promotion").label("storage_source"),
        case(
            (PromotionEvent.event_type.in_(CLIENT_EVENT_TYPES), literal("client")),
            else_=literal("server"),
        ).label("record_source"),
        PromotionEvent.id.label("record_id"),
        PromotionEvent.public_id.label("public_id"),
        PromotionEvent.channel_id.label("channel_id"),
        cast(literal(None), BigInteger).label("template_id"),
        cast(literal(None), BigInteger).label("integration_id"),
        cast(literal(None), String).label("integration_version"),
        PromotionEvent.event_type.label("event_type"),
        func.coalesce(
            _json_text(landing_metadata, "failureDetail", "title"),
            _json_text(landing_metadata, "reasonLabel"),
        ).label("failure_label"),
        PromotionEvent.idempotency_key.label("idempotency_key"),
        PromotionEvent.promotion_visitor_id.label("promotion_visitor_id"),
        PromotionEvent.source_ip.label("source_ip"),
        PromotionEvent.visitor_country_code.label("visitor_country_code"),
        PromotionEvent.network_source.label("network_source"),
        func.coalesce(
            _json_text(landing_metadata, "trafficSource"), literal("direct")
        ).label("traffic_source"),
        PromotionEvent.occurred_at.label("occurred_at"),
        _json_text(landing_request_context, "userAgent").label("user_agent"),
        cast(
            _json_value(landing_metadata, "clientContext", "viewport"),
            String,
        ).label("viewport_json"),
        PromotionEvent.lead_id.label("lead_id"),
    ).where(
        PromotionEvent.channel_id.in_(channel_ids),
        PromotionEvent.occurred_at >= start,
        PromotionEvent.occurred_at < end,
    )
    integration = select(
        literal("integration").label("storage_source"),
        literal("integration").label("record_source"),
        PromotionIntegrationEvent.id.label("record_id"),
        PromotionIntegrationEvent.public_id.label("public_id"),
        PromotionIntegrationEvent.channel_id.label("channel_id"),
        PromotionIntegrationEvent.template_id.label("template_id"),
        PromotionIntegrationEvent.integration_id.label("integration_id"),
        PromotionIntegrationEvent.integration_version.label("integration_version"),
        PromotionIntegrationEvent.event_type.label("event_type"),
        cast(literal(None), String).label("failure_label"),
        PromotionIntegrationEvent.idempotency_key.label("idempotency_key"),
        PromotionIntegrationEvent.promotion_visitor_id.label("promotion_visitor_id"),
        PromotionIntegrationEvent.source_ip.label("source_ip"),
        PromotionIntegrationEvent.visitor_country_code.label("visitor_country_code"),
        PromotionIntegrationEvent.network_source.label("network_source"),
        PromotionIntegrationEvent.traffic_source.label("traffic_source"),
        PromotionIntegrationEvent.occurred_at.label("occurred_at"),
        _json_text(integration_request_context, "userAgent").label("user_agent"),
        cast(
            _json_value(integration_metadata, "clientContext", "viewport"),
            String,
        ).label("viewport_json"),
        cast(literal(None), BigInteger).label("lead_id"),
    ).where(
        PromotionIntegrationEvent.channel_id.in_(channel_ids),
        PromotionIntegrationEvent.occurred_at >= start,
        PromotionIntegrationEvent.occurred_at < end,
    )
    return union_all(landing, integration).subquery("promotion_monitoring_records")


def _device_type_expression(user_agent):
    return case(
        (
            or_(user_agent.ilike("%iPad%"), user_agent.ilike("%Tablet%")),
            literal("tablet"),
        ),
        (
            or_(
                user_agent.ilike("%Mobile%"),
                user_agent.ilike("%iPhone%"),
                user_agent.ilike("%Android%"),
            ),
            literal("mobile"),
        ),
        else_=literal("desktop"),
    )


def _device_system_expression(user_agent):
    return case(
        (
            or_(user_agent.ilike("%iPhone%"), user_agent.ilike("%iPad%")),
            literal("ios"),
        ),
        (user_agent.ilike("%Android%"), literal("android")),
        (user_agent.ilike("%Windows%"), literal("windows")),
        (
            or_(
                user_agent.ilike("%Macintosh%"),
                user_agent.ilike("%Mac OS%"),
            ),
            literal("macos"),
        ),
        (user_agent.ilike("%Linux%"), literal("linux")),
        else_=None,
    )


def _record_device(mapping) -> dict[str, Any]:
    return _device_summary(
        {
            "requestContext": {"userAgent": mapping["user_agent"]},
            "clientContext": {
                "viewport": _normalized_viewport(mapping["viewport_json"])
            },
        }
    )


def _record_row(mapping) -> dict[str, Any]:
    channel: PromotionChannel = mapping[PromotionChannel]
    template: PromotionTemplate | None = mapping[PromotionTemplate]
    domain: DomainRecord | None = mapping[DomainRecord]
    integration: PromotionIntegration | None = mapping[PromotionIntegration]
    visitor: PromotionVisitor | None = mapping[PromotionVisitor]
    source = str(mapping["record_source"])
    event_type = str(mapping["event_type"])
    return {
        "id": entity_id(mapping["record_id"]),
        "source": source,
        "sourceLabel": SOURCE_LABELS[source],
        "eventType": event_type,
        "eventLabel": EVENT_LABELS.get(event_type, event_type),
        "failureLabel": mapping["failure_label"],
        "trafficSource": str(mapping["traffic_source"] or "direct"),
        "occurredAt": iso(mapping["occurred_at"]),
        "visitorId": entity_id(visitor) if visitor else None,
        "fingerprintQuality": visitor.fingerprint_quality if visitor else None,
        "sourceIp": mapping["source_ip"],
        "visitorCountryCode": mapping["visitor_country_code"],
        "networkSource": mapping["network_source"],
        "device": _record_device(mapping),
        "channel": {
            "id": entity_id(channel),
            "name": channel.name,
            "slug": channel.slug,
            "countryCode": channel.country_code,
        },
        "template": {
            "id": entity_id(template) if template else None,
            "name": template.name if template else None,
            "version": template.version if template else None,
        },
        "integration": (
            {
                "id": entity_id(integration),
                "name": integration.name,
                "version": mapping["integration_version"],
            }
            if integration
            else None
        ),
        "landing": _landing(channel, domain),
        "leadId": entity_id(mapping["lead_id"]) if mapping["lead_id"] else None,
    }


def _detail_common(
    *,
    source: str,
    event,
    channel: PromotionChannel,
    template: PromotionTemplate | None,
    domain: DomainRecord | None,
    integration: PromotionIntegration | None = None,
    visitor: PromotionVisitor | None = None,
) -> dict[str, Any]:
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    encoded = json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8")
    event_type = str(event.event_type)
    traffic_source = (
        event.traffic_source
        if isinstance(event, PromotionIntegrationEvent)
        else str(metadata.get("trafficSource") or "direct")
    )
    return {
        "id": entity_id(event),
        "publicId": event.public_id,
        "source": source,
        "sourceLabel": SOURCE_LABELS[source],
        "eventType": event_type,
        "eventLabel": EVENT_LABELS.get(event_type, event_type),
        "idempotencyKey": event.idempotency_key,
        "trafficSource": traffic_source,
        "occurredAt": iso(event.occurred_at),
        "visitorId": entity_id(visitor) if visitor else None,
        "fingerprintVersion": visitor.fingerprint_version if visitor else None,
        "fingerprintQuality": visitor.fingerprint_quality if visitor else None,
        "device": _device_summary(
            {
                "requestContext": event.request_context_json,
                "clientContext": metadata.get("clientContext"),
            }
        ),
        "requestContext": event.request_context_json,
        "clientContext": metadata.get("clientContext") or {},
        "countryCode": event.country_code,
        "sourceIp": event.source_ip,
        "visitorCountryCode": event.visitor_country_code,
        "networkSource": event.network_source,
        "channel": {
            "id": entity_id(channel),
            "name": channel.name,
            "slug": channel.slug,
            "countryCode": channel.country_code,
        },
        "template": {
            "id": entity_id(template) if template else None,
            "name": template.name if template else None,
            "version": template.version if template else None,
        },
        "integration": (
            {
                "id": entity_id(integration),
                "name": integration.name,
                "version": event.integration_version,
            }
            if integration
            else None
        ),
        "landing": _landing(channel, domain),
        "leadId": (
            entity_id(event.lead_id)
            if isinstance(event, PromotionEvent) and event.lead_id
            else None
        ),
        "metadata": metadata,
        "metadataBytes": len(encoded),
    }


@router.get("/records")
def list_records(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    source: str = "all",
    event_type: str = Query(default="all", alias="eventType"),
    traffic_source: str = Query(default="all", alias="trafficSource"),
    visitor_country_code: str = Query(default="all", alias="visitorCountryCode"),
    channel_id: str | None = Query(default=None, alias="channelId"),
    template_id: str | None = Query(default=None, alias="templateId"),
    integration_id: str | None = Query(default=None, alias="integrationId"),
    source_ip: str | None = Query(default=None, alias="sourceIp"),
    device_type: Literal["all", "mobile", "tablet", "desktop"] = Query(
        default="all", alias="deviceType"
    ),
    device_system: Literal[
        "all", "ios", "android", "windows", "macos", "linux", "unknown"
    ] = Query(default="all", alias="deviceSystem"),
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    sort_by: Literal[
        "id",
        "visitorCountryCode",
        "eventType",
        "source",
        "channelName",
        "templateName",
        "integrationName",
        "deviceType",
        "deviceSystem",
        "trafficSource",
        "occurredAt",
    ] = Query(default="id", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query(default="desc", alias="sortOrder"),
) -> dict:
    if source not in {"all", *SOURCE_LABELS}:
        raise HTTPException(status_code=422, detail="记录来源无效")
    if traffic_source not in {"all", "direct", "fission"}:
        raise HTTPException(status_code=422, detail="流量来源无效")
    visitor_country_code = visitor_country_code.strip().upper()
    if visitor_country_code != "ALL" and not re.fullmatch(
        r"[A-Z]{2}", visitor_country_code
    ):
        raise HTTPException(status_code=422, detail="访客国家无效")
    if event_type != "all" and not 1 <= len(event_type) <= 64:
        raise HTTPException(status_code=422, detail="事件类型无效")
    start, end = _range(date_from, date_to)
    channel_ids = _visible_channel_ids(db, current_user)
    if not channel_ids:
        return {"data": {"rows": [], "total": 0, "page": page, "pageSize": page_size}}

    records = _monitoring_sources(channel_ids, start, end)
    device_type_expression = _device_type_expression(records.c.user_agent)
    device_system_expression = _device_system_expression(records.c.user_agent)
    statement = (
        select(
            records,
            PromotionChannel,
            PromotionTemplate,
            DomainRecord,
            PromotionIntegration,
            PromotionVisitor,
        )
        .join(PromotionChannel, PromotionChannel.id == records.c.channel_id)
        .outerjoin(PromotionTemplate, PromotionTemplate.id == PromotionChannel.template_id)
        .outerjoin(DomainRecord, DomainRecord.id == PromotionChannel.domain_id)
        .outerjoin(PromotionIntegration, PromotionIntegration.id == records.c.integration_id)
        .outerjoin(
            PromotionVisitor,
            PromotionVisitor.id == records.c.promotion_visitor_id,
        )
    )
    if source != "all":
        statement = statement.where(records.c.record_source == source)
    if event_type != "all":
        statement = statement.where(records.c.event_type == event_type)
    if traffic_source != "all":
        statement = statement.where(records.c.traffic_source == traffic_source)
    if visitor_country_code != "ALL":
        statement = statement.where(
            records.c.visitor_country_code == visitor_country_code
        )
    if channel_id:
        statement = statement.where(identifier_filter(PromotionChannel, channel_id))
    if template_id:
        statement = statement.where(identifier_filter(PromotionTemplate, template_id))
    if integration_id:
        integration = db.scalar(
            select(PromotionIntegration).where(
                identifier_filter(PromotionIntegration, integration_id)
            )
        )
        if integration is None or (
            current_user.role != "admin" and integration.created_by != current_user.id
        ):
            raise HTTPException(status_code=404, detail="推广集成不存在")
        statement = statement.where(records.c.integration_id == integration.id)
    if source_ip and source_ip.strip():
        statement = statement.where(records.c.source_ip.ilike(f"%{source_ip.strip()}%"))
    if device_type != "all":
        statement = statement.where(device_type_expression == device_type)
    if device_system == "unknown":
        statement = statement.where(device_system_expression.is_(None))
    elif device_system != "all":
        statement = statement.where(device_system_expression == device_system)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                cast(records.c.record_id, String).ilike(pattern),
                cast(records.c.promotion_visitor_id, String).ilike(pattern),
                records.c.source_ip.ilike(pattern),
                records.c.visitor_country_code.ilike(pattern),
                records.c.event_type.ilike(pattern),
                PromotionChannel.name.ilike(pattern),
                PromotionChannel.slug.ilike(pattern),
                PromotionTemplate.name.ilike(pattern),
                DomainRecord.hostname.ilike(pattern),
                PromotionIntegration.name.ilike(pattern),
            )
        )

    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    sort_columns = {
        "id": records.c.record_id,
        "visitorCountryCode": records.c.visitor_country_code,
        "eventType": records.c.event_type,
        "source": records.c.record_source,
        "channelName": PromotionChannel.name,
        "templateName": PromotionTemplate.name,
        "integrationName": PromotionIntegration.name,
        "deviceType": device_type_expression,
        "deviceSystem": device_system_expression,
        "trafficSource": records.c.traffic_source,
        "occurredAt": records.c.occurred_at,
    }
    sort_column = sort_columns[sort_by]
    order_expression = (
        sort_column.desc().nullslast()
        if sort_order == "desc"
        else sort_column.asc().nullslast()
    )
    result = db.execute(
        statement.order_by(
            order_expression,
            records.c.record_id.asc()
            if sort_order == "asc"
            else records.c.record_id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": {
            "rows": [_record_row(row._mapping) for row in result],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "range": {
                "dateFrom": start.date().isoformat(),
                "dateTo": (end - timedelta(days=1)).date().isoformat(),
            },
        }
    }


@router.get("/records/{source}/{record_id}")
def get_record(
    source: str,
    record_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    if source not in SOURCE_LABELS or not 1 <= len(record_id) <= 64:
        raise HTTPException(status_code=404, detail="监控记录不存在")

    if source == "integration":
        statement = (
            select(PromotionIntegrationEvent)
            .join(PromotionChannel, PromotionChannel.id == PromotionIntegrationEvent.channel_id)
            .where(identifier_filter(PromotionIntegrationEvent, record_id))
        )
        if current_user.role != "admin":
            statement = statement.where(PromotionChannel.created_by == current_user.id)
        event = db.scalar(statement)
        if event is None:
            raise HTTPException(status_code=404, detail="监控记录不存在")
        channel = db.get(PromotionChannel, event.channel_id)
        template = db.get(PromotionTemplate, event.template_id or channel.template_id)
        domain = db.get(DomainRecord, channel.domain_id) if channel.domain_id else None
        integration = db.get(PromotionIntegration, event.integration_id)
        visitor = (
            db.get(PromotionVisitor, event.promotion_visitor_id)
            if event.promotion_visitor_id is not None
            else None
        )
        record = _detail_common(
            source=source,
            event=event,
            channel=channel,
            template=template,
            domain=domain,
            integration=integration,
            visitor=visitor,
        )
    else:
        statement = (
            select(PromotionEvent)
            .join(PromotionChannel, PromotionChannel.id == PromotionEvent.channel_id)
            .where(identifier_filter(PromotionEvent, record_id))
        )
        if current_user.role != "admin":
            statement = statement.where(PromotionChannel.created_by == current_user.id)
        event = db.scalar(statement)
        if event is None:
            raise HTTPException(status_code=404, detail="监控记录不存在")
        expected_source = "client" if event.event_type in CLIENT_EVENT_TYPES else "server"
        if source != expected_source:
            raise HTTPException(status_code=404, detail="监控记录不存在")
        channel = db.get(PromotionChannel, event.channel_id)
        template = db.get(PromotionTemplate, channel.template_id)
        domain = db.get(DomainRecord, channel.domain_id) if channel.domain_id else None
        visitor = (
            db.get(PromotionVisitor, event.promotion_visitor_id)
            if event.promotion_visitor_id is not None
            else None
        )
        record = _detail_common(
            source=source,
            event=event,
            channel=channel,
            template=template,
            domain=domain,
            visitor=visitor,
        )
    return {"data": {"record": record}}


@router.get("/options")
def monitoring_options(db: DbSession, current_user: CurrentUser) -> dict:
    channel_ids = _visible_channel_ids(db, current_user)
    channels = list(
        db.scalars(
            select(PromotionChannel)
            .where(PromotionChannel.id.in_(channel_ids))
            .order_by(PromotionChannel.name)
        ).all()
    )
    template_ids = {channel.template_id for channel in channels}
    templates = list(
        db.scalars(
            select(PromotionTemplate)
            .where(PromotionTemplate.id.in_(template_ids))
            .order_by(PromotionTemplate.name)
        ).all()
    )
    landing_types = set(
        db.scalars(
            select(PromotionEvent.event_type)
            .where(PromotionEvent.channel_id.in_(channel_ids))
            .distinct()
        ).all()
    )
    integration_types = set(
        db.scalars(
            select(PromotionIntegrationEvent.event_type)
            .where(PromotionIntegrationEvent.channel_id.in_(channel_ids))
            .distinct()
        ).all()
    )
    integration_ids = select(PromotionIntegrationEvent.integration_id).where(
        PromotionIntegrationEvent.channel_id.in_(channel_ids)
    )
    integrations = list(
        db.scalars(
            select(PromotionIntegration)
            .where(PromotionIntegration.id.in_(integration_ids))
            .order_by(PromotionIntegration.name, PromotionIntegration.id)
        ).all()
    )
    event_types = sorted(landing_types | integration_types)
    country_rows = db.scalars(
        select(PromotionEvent.visitor_country_code)
        .where(
            PromotionEvent.channel_id.in_(channel_ids),
            PromotionEvent.visitor_country_code.is_not(None),
        )
        .union(
            select(PromotionIntegrationEvent.visitor_country_code).where(
                PromotionIntegrationEvent.channel_id.in_(channel_ids),
                PromotionIntegrationEvent.visitor_country_code.is_not(None),
            )
        )
    ).all()
    return {
        "data": {
            "channels": [
                {"id": entity_id(channel), "name": channel.name}
                for channel in channels
            ],
            "templates": [
                {
                    "id": entity_id(template),
                    "name": template.name,
                    "version": template.version,
                }
                for template in templates
            ],
            "eventTypes": [
                {"value": value, "label": EVENT_LABELS.get(value, value)}
                for value in event_types
            ],
            "integrations": [
                {"id": entity_id(integration), "name": integration.name}
                for integration in integrations
            ],
            "visitorCountries": sorted({str(value) for value in country_rows}),
        }
    }
