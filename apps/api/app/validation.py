from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException


PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$")
BLOCKED_JSON_KEYS = {"html", "rawhtml", "script", "code", "servercode", "iframe"}
PROMOTION_INTEGRATION_METADATA_MAX_BYTES = 1024 * 1024
PROMOTION_INTEGRATION_EVENT_MAX_BYTES = PROMOTION_INTEGRATION_METADATA_MAX_BYTES + 64 * 1024


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    normalized = "+" + re.sub(r"\D", "", raw)
    if not PHONE_RE.fullmatch(normalized):
        raise ValueError("手机号必须是有效的 E.164 格式")
    return normalized


def normalize_country(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    normalized = str(value).strip().upper()
    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError("国家代码必须是两个字母")
    return normalized


def normalize_slug(value: str) -> str:
    slug = str(value or "").strip().lower()
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("slug 只能包含小写字母、数字和连字符")
    return slug


def validate_structured_json(value: Any, *, max_bytes: int = 65536) -> dict:
    if not isinstance(value, dict):
        raise ValueError("contentJson 必须是 JSON 对象")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("JSON 内容过大")

    def walk(item: Any, depth: int) -> None:
        if depth > 8:
            raise ValueError("JSON 嵌套层级过深")
        if isinstance(item, dict):
            if len(item) > 200:
                raise ValueError("JSON 对象字段过多")
            for key, child in item.items():
                normalized_key = str(key).replace("_", "").replace("-", "").lower()
                if normalized_key in BLOCKED_JSON_KEYS:
                    raise ValueError("不允许提交 HTML、脚本或服务端代码字段")
                walk(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 1000:
                raise ValueError("JSON 数组过长")
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str):
            lowered = item.lower()
            if "<script" in lowered or "javascript:" in lowered:
                raise ValueError("不允许提交可执行脚本")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError("JSON 包含不支持的数据类型")

    walk(value, 0)
    return value


def validate_integration_metadata(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("metadata 必须是 JSON 对象")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("metadata 包含不支持的 JSON 数据") from error
    if len(encoded.encode("utf-8")) > PROMOTION_INTEGRATION_METADATA_MAX_BYTES:
        raise ValueError("集成回传 metadata 不能超过 1 MiB")

    def walk(item: Any, depth: int) -> None:
        if depth > 16:
            raise ValueError("metadata 嵌套层级过深")
        if isinstance(item, dict):
            for child in item.values():
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif item is not None and not isinstance(item, (bool, int, float, str)):
            raise ValueError("metadata 包含不支持的 JSON 数据")

    walk(value, 0)
    return value


def parse_public_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if normalized > now.replace(microsecond=0) and (normalized - now).total_seconds() > 300:
        raise HTTPException(status_code=422, detail="事件时间不能超过当前时间五分钟")
    return normalized
