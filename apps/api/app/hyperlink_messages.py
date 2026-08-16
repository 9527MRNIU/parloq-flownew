from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from app.validation import normalize_phone, validate_structured_json


HEADER_TYPES = {"none", "text", "image", "video", "document"}
BUTTON_TYPES = {"quick_reply", "url", "call", "copy", "single_select"}
MEDIA_HEADER_TYPES = {"image", "video", "document"}
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]{0,63})\s*\}\}")
SAFE_BUTTON_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _text(value: Any, *, maximum: int, label: str, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{label}不能为空")
    if len(result) > maximum:
        raise ValueError(f"{label}最多{maximum}字符")
    return result


def _http_url(value: Any, *, label: str, https_only: bool = False) -> str:
    result = str(value or "").strip()
    if not result:
        return ""
    parsed = urlsplit(result)
    allowed = {"https"} if https_only else {"http", "https"}
    if (
        parsed.scheme.lower() not in allowed
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{label}必须是有效的{' HTTPS' if https_only else ' HTTP(S)'}地址")
    return result


def _button(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("按钮格式不正确")
    button_type = str(raw.get("type") or "").strip().lower()
    if button_type not in BUTTON_TYPES:
        raise ValueError("暂不支持该按钮类型")
    text = _text(raw.get("text"), maximum=25, label="按钮文本", required=True)
    result: dict[str, Any] = {"type": button_type, "text": text}

    if button_type == "quick_reply":
        button_id = str(raw.get("id") or f"reply_{index + 1}").strip()
        if not SAFE_BUTTON_ID.fullmatch(button_id):
            raise ValueError("快捷回复 ID 格式不正确")
        result["id"] = button_id
    elif button_type == "url":
        result["url"] = _http_url(raw.get("url"), label="按钮链接")
        if not result["url"]:
            raise ValueError("按钮链接不能为空")
    elif button_type == "call":
        phone = normalize_phone(str(raw.get("phone") or ""))
        result["phone"] = phone.lstrip("+")
    elif button_type == "copy":
        result["copyText"] = _text(
            raw.get("copyText"), maximum=256, label="复制内容", required=True
        )
    else:
        sections = raw.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError("单选菜单至少需要一个分组")
        normalized_sections: list[dict[str, Any]] = []
        row_count = 0
        seen_ids: set[str] = set()
        for section_index, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError("单选菜单分组格式不正确")
            title = _text(
                section.get("title") or f"选项 {section_index + 1}",
                maximum=60,
                label="菜单分组标题",
                required=True,
            )
            rows = section.get("rows")
            if not isinstance(rows, list) or not rows:
                raise ValueError("单选菜单分组至少需要一个选项")
            normalized_rows: list[dict[str, str]] = []
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError("单选菜单选项格式不正确")
                row_id = str(row.get("id") or f"option_{row_count + 1}").strip()
                if not SAFE_BUTTON_ID.fullmatch(row_id) or row_id in seen_ids:
                    raise ValueError("单选菜单选项 ID 格式不正确或重复")
                seen_ids.add(row_id)
                normalized_rows.append(
                    {
                        "id": row_id,
                        "title": _text(
                            row.get("title") or f"选项 {row_index + 1}",
                            maximum=80,
                            label="菜单选项标题",
                            required=True,
                        ),
                        "description": _text(
                            row.get("description"),
                            maximum=120,
                            label="菜单选项说明",
                        ),
                    }
                )
                row_count += 1
                if row_count > 10:
                    raise ValueError("单选菜单最多10个选项")
            normalized_sections.append({"title": title, "rows": normalized_rows})
        result["sections"] = normalized_sections
    return result


def validate_hyperlink_template_content(value: dict[str, Any]) -> dict[str, Any]:
    content = validate_structured_json(value, max_bytes=32 * 1024)
    if not isinstance(content, dict):
        raise ValueError("模板内容格式不正确")

    # Backward-compatible normalization for the original text-only templates.
    if not isinstance(content.get("body"), dict):
        legacy_text = content.get("text") or content.get("message") or ""
        content = {
            "version": 1,
            "header": {"type": "none"},
            "body": {"text": legacy_text},
            "footer": {"text": ""},
            "buttons": [],
        }

    header_input = content.get("header")
    header_input = header_input if isinstance(header_input, dict) else {"type": "none"}
    header_type = str(header_input.get("type") or "none").strip().lower()
    if header_type not in HEADER_TYPES:
        raise ValueError("暂不支持该页头类型")
    header: dict[str, Any] = {"type": header_type}
    if header_type == "text":
        header["text"] = _text(
            header_input.get("text"), maximum=60, label="页头", required=True
        )

    body_input = content.get("body")
    body_input = body_input if isinstance(body_input, dict) else {}
    body = {
        "text": _text(
            body_input.get("text"), maximum=4096, label="正文", required=True
        )
    }
    footer_input = content.get("footer")
    footer_input = footer_input if isinstance(footer_input, dict) else {}
    footer = {"text": _text(footer_input.get("text"), maximum=60, label="页脚")}

    raw_buttons = content.get("buttons") or []
    if not isinstance(raw_buttons, list):
        raise ValueError("按钮格式不正确")
    if len(raw_buttons) > 3:
        raise ValueError("按钮最多3个")
    buttons = [_button(raw, index) for index, raw in enumerate(raw_buttons)]
    if any(item["type"] == "single_select" for item in buttons) and len(buttons) != 1:
        raise ValueError("单选菜单不能与其他按钮混用")
    labels = [item["text"].casefold() for item in buttons]
    if len(labels) != len(set(labels)):
        raise ValueError("按钮文本不能重复")

    fallback = _text(
        content.get("fallbackText"), maximum=4096, label="降级文案"
    )
    return {
        "version": 1,
        "header": header,
        "body": body,
        "footer": footer,
        "buttons": buttons,
        **({"fallbackText": fallback} if fallback else {}),
    }


def _render(value: str, variables: dict[str, Any]) -> str:
    return VARIABLE_PATTERN.sub(
        lambda match: str(variables.get(match.group(1), ""))[:500], value
    )


def render_hyperlink_message(
    content: dict[str, Any],
    variables: dict[str, Any],
    *,
    material_type: str | None = None,
    material_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = deepcopy(validate_hyperlink_template_content(content))
    header = message["header"]
    if header["type"] in MEDIA_HEADER_TYPES:
        if material_type != header["type"] or not isinstance(material_reference, dict):
            raise ValueError("媒体页头需要选择已上传的同类型素材")
        header["media"] = material_reference

    def walk(raw: Any) -> Any:
        if isinstance(raw, str):
            return _render(raw, variables)
        if isinstance(raw, list):
            return [walk(item) for item in raw]
        if isinstance(raw, dict):
            return {key: walk(item) for key, item in raw.items()}
        return raw

    return walk(message)
