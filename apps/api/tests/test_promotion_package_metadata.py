from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient


def _zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def _v3_template_manifest(**metadata: str) -> dict:
    return {
        "schema": "promotion-template/v3",
        "version": metadata.pop("version", "1.0.0"),
        **metadata,
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
        "supportedLocales": ["en"],
        "i18n": {
            "mode": "bundled",
            "path": "locales/{locale}.json",
            "fallbackLocale": "en",
        },
    }


def test_template_package_metadata_can_prefill_and_be_overridden(
    admin_client: TestClient,
) -> None:
    package = _zip(
        {
            "index.html": '<html><head></head><body>模板<script src="assets/account-link-elements.js"></script></body></html>',
            "assets/account-link-elements.js": "window.testComponents = true;",
            "locales/en.json": "{}",
            "manifest.json": json.dumps(
                _v3_template_manifest(
                    version="2.3.0",
                    name="中文活动落地页",
                    description="用于中文市场的账号链接活动。",
                ),
                ensure_ascii=False,
            ),
        }
    )

    inspected = admin_client.post(
        "/api/promotion/templates/package-metadata",
        files={"file": ("0001-account-link-2.3.0.zip", package, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["data"]["metadata"] == {
        "name": "中文活动落地页",
        "description": "用于中文市场的账号链接活动。",
        "version": "2.3.0",
    }

    imported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "手动修改后的名称", "description": "手动修改后的说明"},
        files={"file": ("0001-account-link-2.3.0.zip", package, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    template = imported.json()["data"]["template"]
    assert template["name"] == "手动修改后的名称"
    assert template["description"] == "手动修改后的说明"
    assert template["manifest"]["name"] == "中文活动落地页"


def test_integration_package_metadata_can_prefill_import_form(
    admin_client: TestClient,
) -> None:
    package = _zip(
        {
            "scripts/runtime.js": "window.packageMetadata = true;",
            "integration.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "type": "script",
                    "version": "1.5.0",
                    "integrationKey": "visitor-link-v1",
                    "name": "统一访客关联",
                    "description": "为推广模板提供统一的访客关联能力。",
                    "entry": "scripts/runtime.js",
                },
                ensure_ascii=False,
            ),
        }
    )

    inspected = admin_client.post(
        "/api/promotion/integrations/package-metadata",
        files={"file": ("0002-visitor-link-1.5.0.zip", package, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["data"]["metadata"] == {
        "integrationKey": "visitor-link-v1",
        "name": "统一访客关联",
        "description": "为推广模板提供统一的访客关联能力。",
        "version": "1.5.0",
        "type": "script",
    }


def test_package_metadata_rejects_invalid_management_fields(
    admin_client: TestClient,
) -> None:
    invalid_template = _zip(
        {
            "index.html": "<html></html>",
            "manifest.json": json.dumps({"name": {"zh-CN": "不是字符串"}}),
        }
    )
    template_response = admin_client.post(
        "/api/promotion/templates/package-metadata",
        files={"file": ("invalid.zip", invalid_template, "application/zip")},
    )
    assert template_response.status_code == 422
    assert "模板名称必须是字符串" in template_response.text

    invalid_integration = _zip(
        {
            "runtime.js": "window.invalidMetadata = true;",
            "integration.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "integrationKey": "Uppercase-Key",
                    "name": "无效集成",
                },
                ensure_ascii=False,
            ),
        }
    )
    integration_response = admin_client.post(
        "/api/promotion/integrations/package-metadata",
        files={"file": ("invalid.zip", invalid_integration, "application/zip")},
    )
    assert integration_response.status_code == 422
    assert "集成标识只能包含小写字母" in integration_response.text
