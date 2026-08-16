from __future__ import annotations

from typing import Any, Literal

from app.validation import validate_structured_json


TextMaterialRole = Literal["body", "header", "footer", "button"]

TEXT_MATERIAL_ROLES: tuple[str, ...] = ("body", "header", "footer", "button")
TEXT_ROLE_LIMITS: dict[str, int] = {
    "body": 4096,
    "header": 60,
    "footer": 60,
    "button": 25,
}
TEXT_ROLE_LABELS: dict[str, str] = {
    "body": "正文",
    "header": "页头",
    "footer": "页脚",
    "button": "按钮",
}


def normalize_text_role(value: Any, *, required: bool = True) -> str | None:
    role = str(value or "").strip().lower()
    if not role and not required:
        return None
    if role not in TEXT_MATERIAL_ROLES:
        raise ValueError("文本用途必须是正文、页头、页脚或按钮")
    return role


def validate_text_material_content(value: Any, role: str) -> dict[str, str]:
    content = validate_structured_json(value)
    normalized_role = normalize_text_role(role)
    assert normalized_role is not None
    maximum = TEXT_ROLE_LIMITS[normalized_role]
    label = TEXT_ROLE_LABELS[normalized_role]

    result: dict[str, str] = {}
    for key, field_label in (
        ("originalText", "原文"),
        ("translatedText", "译文"),
    ):
        source = content.get(key)
        if key == "originalText" and source in (None, ""):
            source = content.get("text")
        text = str(source or "").strip()
        if key == "originalText" and not text:
            raise ValueError(f"{label}{field_label}不能为空")
        if not text:
            result[key] = ""
            continue
        if normalized_role != "body" and ("\n" in text or "\r" in text):
            raise ValueError(f"{label}{field_label}必须是单行文本")
        if len(text) > maximum:
            raise ValueError(f"{label}{field_label}最多{maximum}字符")
        result[key] = text
    return result
