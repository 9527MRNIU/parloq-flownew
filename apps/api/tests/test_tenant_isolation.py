from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import ProxyEndpoint


def _create_operator(admin: TestClient, username: str) -> None:
    groups = admin.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    response = admin.post(
        "/api/users",
        json={
            "username": username,
            "password": "operator-pass-123",
            "groupId": operator["id"],
        },
    )
    assert response.status_code == 201, response.text


def _login(username: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "operator-pass-123"},
    )
    assert response.status_code == 200
    return client


def test_operators_cannot_see_each_others_links_or_accounts(
    admin_client: TestClient,
) -> None:
    # Existing global pool rows from other tests must not influence this
    # allocation assertion; unhealthy endpoints are deliberately ineligible.
    with SessionLocal() as db:
        for existing in db.scalars(select(ProxyEndpoint)).all():
            existing.health_status = "unhealthy"
        db.commit()
    proxy = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Tenant Auto US",
            "protocol": "socks5",
            "host": "tenant-auto-us.example",
            "port": 1080,
            "username": "private-username",
            "password": "private-password",
            "countryCode": "US",
        },
    )
    assert proxy.status_code == 201
    proxy_id = proxy.json()["data"]["proxy"]["id"]
    assert admin_client.post(f"/api/ip-proxies/{proxy_id}/test").json()["data"]["proxy"]["healthStatus"] == "healthy"
    _create_operator(admin_client, "tenant-links-a")
    _create_operator(admin_client, "tenant-links-b")
    first = _login("tenant-links-a")
    second = _login("tenant-links-b")
    try:
        link = first.post(
            "/api/direct-short-links",
            json={"title": "private", "targetUrl": "https://example.com/a"},
        )
        assert link.status_code == 201
        account = first.post(
            "/api/personal-accounts",
            json={"name": "Tenant A", "phone": "+12025551001", "countryCode": "US"},
        )
        assert account.status_code == 201
        account_id = account.json()["data"]["account"]["id"]
        own_group = first.post(
            "/api/account-groups", json={"name": "Tenant A accounts"}
        )
        foreign_group = second.post(
            "/api/account-groups", json={"name": "Tenant B accounts"}
        )
        assert own_group.status_code == foreign_group.status_code == 201
        own_group_id = own_group.json()["data"]["group"]["id"]
        foreign_group_id = foreign_group.json()["data"]["group"]["id"]
        assert first.patch(
            f"/api/personal-accounts/{account_id}",
            json={"groupId": own_group_id},
        ).status_code == 200
        # Even a global administrator cannot accidentally cross-link tenant
        # resources while organizing the shared console view.
        cross_group = admin_client.patch(
            f"/api/personal-accounts/{account_id}",
            json={"groupId": foreign_group_id},
        )
        assert cross_group.status_code == 409
        assert cross_group.json()["detail"] == "账号与分组不属于同一客户"
        assert account.json()["data"]["account"]["proxyBinding"]["proxyPublicId"] == proxy_id
        visible_proxies = first.get("/api/ip-proxies").json()["data"]
        assert visible_proxies["total"] == 1
        proxy_row = visible_proxies["rows"][0]
        assert "username" not in proxy_row and "password" not in proxy_row
        assert proxy_row["healthStatus"] == "healthy"
        assert proxy_row["usernameMasked"].endswith("name")
        assert proxy_row["passwordMasked"].endswith("word")
        assert second.get("/api/direct-short-links").json()["data"]["total"] == 0
        assert second.get("/api/personal-accounts").json()["data"]["total"] == 0
        assert second.get(f"/api/personal-accounts/{account_id}").status_code == 404
        assert admin_client.get("/api/direct-short-links").json()["data"]["total"] >= 1
    finally:
        first.close()
        second.close()


def test_operators_cannot_cross_read_business_resources(
    admin_client: TestClient,
) -> None:
    _create_operator(admin_client, "tenant-business-a")
    _create_operator(admin_client, "tenant-business-b")
    first = _login("tenant-business-a")
    second = _login("tenant-business-b")
    try:
        domain = first.post(
            "/api/domains", json={"hostname": "tenant-a-private.example"}
        )
        pixel = first.post(
            "/api/meta-pixels",
            json={"name": "Private Pixel", "datasetId": "tenant-a-dataset"},
        )
        material = first.post(
            "/api/hyperlink/materials",
            json={"name": "Private Material", "type": "text", "contentJson": {"text": "A"}},
        )
        assert domain.status_code == pixel.status_code == material.status_code == 201
        domain_id = domain.json()["data"]["domain"]["id"]
        material_id = material.json()["data"]["material"]["id"]
        assert second.get("/api/domains").json()["data"]["total"] == 0
        assert second.get("/api/meta-pixels").json()["data"]["total"] == 0
        assert second.get("/api/hyperlink/materials").json()["data"]["total"] == 0
        assert second.get(f"/api/domains/{domain_id}").status_code == 404
        assert second.get(f"/api/hyperlink/materials/{material_id}").status_code == 404
        assert second.patch(
            f"/api/hyperlink/materials/{material_id}", json={"name": "stolen"}
        ).status_code == 404
    finally:
        first.close()
        second.close()
