from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ProxyEndpoint


def test_ip_proxy_and_binding_lifecycle(admin_client: TestClient) -> None:
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
    assert proxy["countryCode"] == "US"
    assert proxy["usernameMasked"] == "••••user"
    assert proxy["passwordMasked"] == "••••word"
    assert "customer-user" not in created.text
    assert "very-secret-password" not in created.text
    assert proxy["healthStatus"] == "untested"

    with SessionLocal() as db:
        stored = db.scalar(
            select(ProxyEndpoint).where(ProxyEndpoint.public_id == proxy["id"])
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
        json={"accountPublicId": "waacct_customer_001", "proxyPublicId": proxy["id"]},
    )
    assert first_binding.status_code == 201
    binding_one = first_binding.json()["data"]["binding"]
    second_binding = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountPublicId": "waacct_customer_002", "proxyPublicId": proxy["id"]},
    )
    assert second_binding.status_code == 201
    binding_two = second_binding.json()["data"]["binding"]

    duplicate = admin_client.post(
        "/api/ip-proxy-bindings",
        json={"accountPublicId": "waacct_customer_001", "proxyPublicId": proxy["id"]},
    )
    assert duplicate.status_code == 409
    detail = admin_client.get(f"/api/ip-proxies/{proxy['id']}").json()["data"]["proxy"]
    assert detail["assignedAccountCount"] == 2
    assert admin_client.delete(f"/api/ip-proxies/{proxy['id']}").status_code == 409

    assert admin_client.delete(f"/api/ip-proxy-bindings/{binding_one['id']}").status_code == 200
    assert admin_client.delete(f"/api/ip-proxy-bindings/{binding_two['id']}").status_code == 200
    assert admin_client.delete(f"/api/ip-proxies/{proxy['id']}").status_code == 200


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

    assert admin_client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).status_code == 200
    assert admin_client.delete(f"/api/users/{user_id}").status_code == 200
    assert admin_client.delete(f"/api/user-groups/{group_id}").status_code == 409
