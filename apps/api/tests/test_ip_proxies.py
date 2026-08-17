from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PersonalAccount, ProxyEndpoint
from app.routers.ip_proxies import _reconcile_account_proxy_best_effort
from app.services.wa_gateway import WaGatewayClient


def test_ip_proxy_and_binding_lifecycle(admin_client: TestClient) -> None:
    accounts = []
    for suffix in ("61", "62"):
        response = admin_client.post(
            "/api/personal-accounts",
            json={"name": f"Proxy account {suffix}", "phone": f"+120255500{suffix}"},
        )
        assert response.status_code == 201, response.text
        account = response.json()["data"]["account"]
        if account["proxyBinding"] is not None:
            assert admin_client.delete(
                f"/api/ip-proxy-bindings/{account['proxyBinding']['bindingId']}"
            ).status_code == 200
        accounts.append(account)
    default_policy = admin_client.get("/api/ip-allocation-policy")
    assert default_policy.status_code == 200
    assert default_policy.json()["data"]["policy"]["allocationMode"] == "least_load"
    updated_policy = admin_client.patch(
        "/api/ip-allocation-policy",
        json={
            "allocationMode": "tenant_reuse",
            "countryMatch": "strict",
            "maxAccountsPerIp": 8,
            "avoidUnhealthy": True,
            "stickyBinding": True,
        },
    )
    assert updated_policy.status_code == 200
    assert updated_policy.json()["data"]["policy"]["countryMatch"] == "strict"
    assert updated_policy.json()["data"]["policy"]["maxAccountsPerIp"] == 8
    created = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "US Proxy One",
            "protocol": "socks5",
            "host": "proxy.example.test",
            "port": 1080,
            "username": "customer-user",
            "password": "very-secret-password",
            "countryCode": "us",
            "provider": "Test Provider",
        },
    )
    assert created.status_code == 201
    proxy = created.json()["data"]["proxy"]
    assert proxy["id"].isdecimal()
    assert "publicId" not in proxy
    assert proxy["countryCode"] == "US"
    assert proxy["usernameMasked"] == "••••user"
    assert proxy["passwordMasked"] == "••••word"
    assert "customer-user" not in created.text
    assert "very-secret-password" not in created.text
    assert proxy["healthStatus"] == "untested"

    with SessionLocal() as db:
        stored = db.scalar(
            select(ProxyEndpoint).where(ProxyEndpoint.id == int(proxy["id"]))
        )
        assert stored is not None
        assert "customer-user" not in (stored.username_ciphertext or "")
        assert "very-secret-password" not in (stored.password_ciphertext or "")

    health = admin_client.post(f"/api/ip-proxies/{proxy['id']}/test")
    assert health.status_code == 200
    assert health.json()["data"]["proxy"]["healthStatus"] == "healthy"
    assert health.json()["data"]["proxy"]["lastCheckedAt"] is not None

    first_binding = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountId": accounts[0]["id"], "proxyId": proxy["id"]},
    )
    assert first_binding.status_code == 201
    binding_one = first_binding.json()["data"]["binding"]
    assert binding_one["accountId"] == accounts[0]["id"]
    assert "accountPublicId" not in binding_one
    assert "publicId" not in binding_one
    second_binding = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountId": accounts[1]["id"], "proxyId": proxy["id"]},
    )
    assert second_binding.status_code == 201
    binding_two = second_binding.json()["data"]["binding"]

    duplicate = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountId": accounts[0]["id"], "proxyId": proxy["id"]},
    )
    assert duplicate.status_code == 409
    detail = admin_client.get(f"/api/ip-proxies/{proxy['id']}").json()["data"]["proxy"]
    assert detail["assignedAccountCount"] == 2
    assert admin_client.delete(f"/api/ip-proxies/{proxy['id']}").status_code == 409

    assert admin_client.delete(f"/api/ip-proxy-bindings/{binding_one['id']}").status_code == 200
    assert admin_client.delete(f"/api/ip-proxy-bindings/{binding_two['id']}").status_code == 200
    assert admin_client.delete(f"/api/ip-proxies/{proxy['id']}").status_code == 200


def test_proxy_reconciliation_uses_the_persisted_binding(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    account_response = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Proxy reconcile account", "phone": "+12025550063"},
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()["data"]["account"]
    if account["proxyBinding"] is not None:
        assert admin_client.delete(
            f"/api/ip-proxy-bindings/{account['proxyBinding']['bindingId']}"
        ).status_code == 200
    proxy_response = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Reconcile proxy",
            "protocol": "socks5",
            "host": "proxy-reconcile.example.test",
            "port": 1080,
        },
    )
    assert proxy_response.status_code == 201, proxy_response.text
    proxy = proxy_response.json()["data"]["proxy"]
    binding_response = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountId": account["id"], "proxyId": proxy["id"]},
    )
    assert binding_response.status_code == 201, binding_response.text

    with SessionLocal() as db:
        stored_account = db.get(PersonalAccount, int(account["id"]))
        assert stored_account is not None
        gateway_account_id = stored_account.gateway_account_id

    updates = []

    def record_update(self, account_id, proxy_url):
        updates.append((account_id, proxy_url))
        return {"id": account_id, "state": "linked_offline"}

    monkeypatch.setattr(WaGatewayClient, "update_proxy", record_update)
    _reconcile_account_proxy_best_effort(gateway_account_id)

    assert updates == [
        (gateway_account_id, "socks5://proxy-reconcile.example.test:1080")
    ]


def test_password_can_be_cleared_without_ever_being_returned(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Password Clear Proxy",
            "protocol": "http",
            "host": "198.51.100.10",
            "port": 8080,
            "password": "temporary-password",
        },
    ).json()["data"]["proxy"]
    updated = admin_client.patch(
        f"/api/ip-proxies/{created['id']}", json={"password": ""}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["proxy"]["passwordMasked"] is None
    assert "temporary-password" not in updated.text


def test_bulk_proxy_import_parses_lines_and_reports_partial_results(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/ip-proxies/bulk",
        json={
            "lines": [
                "# one proxy per line",
                "203.0.113.21:8080",
                "203.0.113.22:8081:batch-user:batch-password",
                "encoded-user:encoded%40password@203.0.113.23:1080",
                "socks5://url-user:url-password@203.0.113.24:1081",
                "203.0.113.25:8082:colon-user:p@ss:word",
                "203.0.113.21:8080",
                "invalid-line",
                "",
            ],
            "defaultProtocol": "https",
            "countryCode": "us",
            "provider": "Bulk Provider",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["summary"] == {
        "total": 7,
        "created": 5,
        "duplicate": 1,
        "failed": 1,
    }
    assert [item["status"] for item in data["results"]] == [
        "created",
        "created",
        "created",
        "created",
        "created",
        "duplicate",
        "failed",
    ]
    assert data["results"][-1]["line"] == 8
    assert "batch-password" not in response.text
    assert "url-password" not in response.text
    assert "encoded%40password" not in response.text
    assert "p@ss:word" not in response.text

    rows = data["rows"]
    assert {row["host"] for row in rows} == {
        "203.0.113.21",
        "203.0.113.22",
        "203.0.113.23",
        "203.0.113.24",
        "203.0.113.25",
    }
    assert {row["countryCode"] for row in rows} == {"US"}
    assert {row["provider"] for row in rows} == {"Bulk Provider"}
    assert {row["protocol"] for row in rows} == {"https", "socks5"}

    duplicate = admin_client.post(
        "/api/ip-proxies/bulk",
        json={"lines": ["https://203.0.113.21:8080"]},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["summary"]["duplicate"] == 1
    assert duplicate.json()["data"]["rows"] == []


def test_non_admin_has_read_only_ip_management_access(admin_client: TestClient) -> None:
    group = admin_client.post("/api/user-groups", json={"name": "IP 只读组"})
    assert group.status_code == 201
    group_id = group.json()["data"]["group"]["id"]
    user = admin_client.post(
        "/api/users",
        json={
            "username": "ip-readonly",
            "password": "secure-pass-123",
            "groupId": group_id,
        },
    )
    assert user.status_code == 201
    user_id = user.json()["data"]["user"]["id"]
    token = admin_client.post(
        "/api/auth/login", json={"username": "ip-readonly", "password": "secure-pass-123"}
    ).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert admin_client.get("/api/ip-proxies", headers=headers).status_code == 200
    denied = admin_client.post(
        "/api/ip-proxies",
        json={"name": "Denied", "protocol": "http", "host": "example.com", "port": 80},
        headers=headers,
    )
    assert denied.status_code == 403
    denied_bulk = admin_client.post(
        "/api/ip-proxies/bulk",
        json={"lines": ["203.0.113.50:8080"]},
        headers=headers,
    )
    assert denied_bulk.status_code == 403

    assert admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).status_code == 200
    assert admin_client.delete(f"/api/users/{user_id}").status_code == 200
    assert admin_client.delete(f"/api/user-groups/{group_id}").status_code == 409
