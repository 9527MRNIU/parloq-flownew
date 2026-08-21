from __future__ import annotations

from fastapi.testclient import TestClient

from app.developer_docs import DOC_SECTIONS, page_content
from app.main import app


def test_developer_docs_require_login(client: TestClient) -> None:
    assert client.get("/api/developer-docs").status_code == 401
    assert client.get("/api/developer-docs/overview").status_code == 401


def test_developer_docs_catalog_matches_checked_in_content(
    admin_client: TestClient,
) -> None:
    response = admin_client.get("/api/developer-docs")
    assert response.status_code == 200
    data = response.json()["data"]
    pages = [page for section in data["sections"] for page in section["pages"]]
    assert data["defaultPage"] == "overview"
    assert len(pages) == 29
    assert len([page for page in pages if page["slug"].startswith("menu-")]) == 22

    expected = [page["slug"] for section in DOC_SECTIONS for page in section["pages"]]
    assert [page["slug"] for page in pages] == expected
    assert all(page_content(slug) for slug in expected)


def test_developer_doc_page_returns_markdown_without_unimplemented_features(
    admin_client: TestClient,
) -> None:
    response = admin_client.get("/api/developer-docs/template-runtime")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"]["title"] == "运行时与配对接口"
    assert "PromotionBridge" in data["content"]

    all_content = "\n".join(
        page_content(page["slug"]) or ""
        for section in DOC_SECTIONS
        for page in section["pages"]
    ).lower()
    assert "webhook" not in all_content


def test_unknown_developer_doc_returns_not_found(admin_client: TestClient) -> None:
    assert admin_client.get("/api/developer-docs/not-a-page").status_code == 404


def test_builtin_operator_can_read_docs_without_system_admin_menus(
    admin_client: TestClient,
) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    created = admin_client.post(
        "/api/users",
        json={
            "username": "docs-operator",
            "password": "secure-pass-123",
            "groupId": operator["id"],
        },
    )
    assert created.status_code == 201

    operator_client = TestClient(app)
    try:
        assert operator_client.post(
            "/api/auth/login",
            json={"username": "docs-operator", "password": "secure-pass-123"},
        ).status_code == 200
        assert operator_client.get("/api/developer-docs").status_code == 200
        menu_tree = operator_client.get("/api/system/menus/me").json()["data"]["tree"]
        permission_keys: set[str] = set()

        def collect(items: list[dict]) -> None:
            for item in items:
                permission_keys.add(item.get("permissionKey") or "")
                collect(item.get("children") or [])

        collect(menu_tree)
        assert "system.developer_docs.read" in permission_keys
        assert "system.users.manage" not in permission_keys
        assert "system.roles.manage" not in permission_keys
        assert "system.menus.manage" not in permission_keys
    finally:
        operator_client.close()
