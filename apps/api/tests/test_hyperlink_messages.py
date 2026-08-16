from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.hyperlink_messages import (
    render_hyperlink_message,
    validate_hyperlink_template_content,
)
from app.material_files import material_delivery_reference
from app.models import Material


def test_legacy_template_is_normalized_and_variables_are_rendered() -> None:
    normalized = validate_hyperlink_template_content({"text": "Hello {{name}}"})
    assert normalized == {
        "version": 1,
        "header": {"type": "none"},
        "body": {"text": "Hello {{name}}"},
        "footer": {"text": ""},
        "buttons": [],
    }
    rendered = render_hyperlink_message(normalized, {"name": "Ada"})
    assert rendered["body"]["text"] == "Hello Ada"


def test_structured_template_resolves_linked_media_and_buttons() -> None:
    media = {
        "id": "4780486454931715",
        "token": "signed-material-token",
        "fileName": "banner.png",
        "mimeType": "image/png",
        "size": 67,
        "sha256": "a" * 64,
    }
    rendered = render_hyperlink_message(
        {
            "header": {"type": "image"},
            "body": {"text": "Hello {{name}}"},
            "footer": {"text": "Terms apply"},
            "buttons": [
                {"type": "url", "text": "View", "url": "https://example.test"},
                {"type": "call", "text": "Call", "phone": "8613800000000"},
                {"type": "copy", "text": "Copy", "copyText": "SAVE20"},
            ],
        },
        {"name": "Ada"},
        material_type="image",
        material_reference=media,
    )
    assert rendered["header"]["media"] == media
    assert "url" not in rendered["header"]
    assert rendered["buttons"][1]["phone"] == "8613800000000"


def test_template_rejects_invalid_interactive_combinations() -> None:
    with pytest.raises(ValueError, match="不能与其他按钮混用"):
        validate_hyperlink_template_content(
            {
                "header": {"type": "none"},
                "body": {"text": "hello"},
                "buttons": [
                    {
                        "type": "single_select",
                        "text": "Choose",
                        "sections": [
                            {"title": "Options", "rows": [{"id": "a", "title": "A"}]}
                        ],
                    },
                    {"type": "quick_reply", "text": "Reply", "id": "reply"},
                ],
            }
        )


def test_template_rejects_media_without_managed_file_at_render_time() -> None:
    with pytest.raises(ValueError, match="媒体页头需要"):
        render_hyperlink_message(
            {
                "header": {"type": "video"},
                "body": {"text": "hello"},
                "buttons": [],
            },
            {},
        )


def test_template_cannot_remove_the_only_media_source(
    admin_client: TestClient,
) -> None:
    material_response = admin_client.post(
        "/api/materials/upload",
        data={"name": "Banner", "type": "image", "enabled": "true"},
        files={
            "file": (
                "banner.png",
                b"\x89PNG\r\n\x1a\n" + b"managed-material",
                "image/png",
            )
        },
    )
    assert material_response.status_code == 201, material_response.text
    material_id = material_response.json()["data"]["material"]["id"]
    template_response = admin_client.post(
        "/api/hyperlink/templates",
        json={
            "name": "Media template",
            "contentJson": {
                "header": {"type": "image"},
                "body": {"text": "hello"},
                "buttons": [],
            },
            "materialId": material_id,
        },
    )
    assert template_response.status_code == 201, template_response.text
    template_id = template_response.json()["data"]["template"]["id"]

    response = admin_client.patch(
        f"/api/hyperlink/templates/{template_id}", json={"materialId": None}
    )
    assert response.status_code == 422
    assert "媒体页头" in response.json()["detail"]


def test_binary_material_is_uploaded_and_served_by_the_system(
    admin_client: TestClient,
) -> None:
    content = b"\x89PNG\r\n\x1a\n" + b"direct-upload"
    created = admin_client.post(
        "/api/materials/upload",
        data={"name": "Uploaded image", "type": "image", "enabled": "true"},
        files={"file": ("photo.png", content, "image/png")},
    )
    assert created.status_code == 201, created.text
    material = created.json()["data"]["material"]
    assert material["hasFile"] is True
    assert material["fileName"] == "photo.png"
    assert material["contentType"] == "image/png"
    assert material["size"] == len(content)
    assert material["sha256"]
    assert material["previewPath"] == f"/api/materials/{material['id']}/content"
    assert "url" not in material["contentJson"]

    served = admin_client.get(material["previewPath"])
    assert served.status_code == 200
    assert served.content == content
    assert served.headers["content-type"] == "image/png"

    with SessionLocal() as db:
        stored = db.get(Material, int(material["id"]))
        assert stored is not None
        reference = material_delivery_reference(stored)
    internal = admin_client.get(
        f"/api/internal/materials/{material['id']}/content",
        headers={"Authorization": f"Bearer {reference['token']}"},
    )
    assert internal.status_code == 200
    assert internal.content == content
    assert admin_client.get(
        f"/api/internal/materials/{material['id']}/content",
        headers={"Authorization": "Bearer invalid"},
    ).status_code == 401


def test_text_material_preserves_original_and_translated_text(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/materials",
        json={
            "name": "Bilingual copy",
            "type": "text",
            "contentJson": {
                "originalText": "Oferta disponível hoje.",
                "translatedText": "优惠今日有效。",
            },
        },
    )
    assert created.status_code == 201, created.text
    material = created.json()["data"]["material"]
    assert material["contentJson"] == {
        "originalText": "Oferta disponível hoje.",
        "translatedText": "优惠今日有效。",
    }
    assert material["textRole"] == "body"

    updated = admin_client.patch(
        f"/api/materials/{material['id']}",
        json={
            "contentJson": {
                "originalText": "Oferta atualizada.",
                "translatedText": "优惠已更新。",
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["material"]["contentJson"] == {
        "originalText": "Oferta atualizada.",
        "translatedText": "优惠已更新。",
    }


def test_text_material_roles_filter_and_validate_content(
    admin_client: TestClient,
) -> None:
    capabilities = admin_client.get("/api/materials/capabilities")
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()["data"]["textRoles"] == [
        {"value": "body", "label": "正文", "maxLength": 4096, "multiline": True},
        {"value": "header", "label": "页头", "maxLength": 60, "multiline": False},
        {"value": "footer", "label": "页脚", "maxLength": 60, "multiline": False},
        {"value": "button", "label": "按钮", "maxLength": 25, "multiline": False},
    ]

    created = admin_client.post(
        "/api/materials",
        json={
            "name": "Open button",
            "type": "text",
            "textRole": "button",
            "contentJson": {
                "originalText": "Open",
                "translatedText": "打开",
            },
        },
    )
    assert created.status_code == 201, created.text
    material = created.json()["data"]["material"]
    assert material["textRole"] == "button"

    filtered = admin_client.get("/api/materials?type=text&textRole=button")
    assert filtered.status_code == 200, filtered.text
    assert [row["id"] for row in filtered.json()["data"]["rows"]] == [material["id"]]

    invalid_multiline = admin_client.post(
        "/api/materials",
        json={
            "name": "Invalid header",
            "type": "text",
            "textRole": "header",
            "contentJson": {
                "originalText": "First line\nSecond line",
                "translatedText": "第一行",
            },
        },
    )
    assert invalid_multiline.status_code == 422

    invalid_role_change = admin_client.patch(
        f"/api/materials/{material['id']}",
        json={
            "textRole": "header",
            "contentJson": {
                "originalText": "x" * 61,
                "translatedText": "标题",
            },
        },
    )
    assert invalid_role_change.status_code == 422


def test_binary_material_cannot_be_created_from_an_external_url(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/materials",
        json={
            "name": "Remote image",
            "type": "image",
            "contentJson": {"url": "https://cdn.example.test/banner.jpg"},
        },
    )
    assert response.status_code == 422
