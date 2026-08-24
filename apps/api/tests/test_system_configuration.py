from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routers.system_configuration as configuration_router
from app.database import SessionLocal
from app.main import app
from app.models import SystemCredential, SystemPlatformConfiguration
from app.security import decrypt_secret


def test_platform_credentials_are_encrypted_and_never_returned(
    admin_client: TestClient,
) -> None:
    secret = "cloudflare-production-token-1234567890"
    admin_client.delete("/api/system/configuration/cloudflare")
    try:
        saved = admin_client.put(
            "/api/system/configuration/cloudflare",
            json={"value": secret, "enabled": True, "accountId": "account-123"},
        )
        assert saved.status_code == 200
        assert saved.headers["cache-control"] == "no-store"
        platform = saved.json()["data"]["platform"]
        assert platform["configured"] is True
        assert platform["maskedValue"] == "••••7890"
        assert platform["enabled"] is True
        assert platform["settings"] == {"accountId": "account-123"}
        assert secret not in saved.text

        with SessionLocal() as db:
            credential = db.scalar(
                select(SystemCredential).where(
                    SystemCredential.platform_key == "cloudflare"
                )
            )
            assert credential is not None
            assert credential.value_ciphertext != secret
            assert decrypt_secret(credential.value_ciphertext) == secret
            config = db.scalar(
                select(SystemPlatformConfiguration).where(
                    SystemPlatformConfiguration.platform_key == "cloudflare"
                )
            )
            assert config is not None
            assert config.enabled is True
            assert config.settings_json == {"accountId": "account-123"}

        listed = admin_client.get("/api/system/configuration")
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "no-store"
        assert secret not in listed.text
        cloudflare = next(
            row
            for row in listed.json()["data"]["platforms"]
            if row["key"] == "cloudflare"
        )
        assert cloudflare["configured"] is True
        assert cloudflare["maskedValue"] == "••••7890"
    finally:
        cleared = admin_client.delete("/api/system/configuration/cloudflare")
        assert cleared.status_code == 200

    with SessionLocal() as db:
        assert db.scalar(
            select(SystemCredential).where(
                SystemCredential.platform_key == "cloudflare"
            )
        ) is None


def test_platform_credentials_reject_unknown_or_short_values(
    admin_client: TestClient,
) -> None:
    assert admin_client.put(
        "/api/system/configuration/unknown",
        json={"value": "long-enough-token"},
    ).status_code == 404
    assert admin_client.put(
        "/api/system/configuration/cloudflare",
        json={"value": "short"},
    ).status_code == 422
    assert admin_client.put(
        "/api/system/configuration/namesilo",
        json={"value": "long-enough-token", "paymentId": "not-numeric"},
    ).status_code == 422
    assert admin_client.put(
        "/api/system/configuration/baota",
        json={"value": "long-enough-token", "baseUrl": "https://user:pass@example.com"},
    ).status_code == 422


def test_enabled_platform_requires_a_saved_credential(admin_client: TestClient) -> None:
    admin_client.delete("/api/system/configuration/namesilo")
    response = admin_client.put(
        "/api/system/configuration/namesilo",
        json={"enabled": True, "paymentId": "2531590"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "请先配置平台凭据"


def test_namesilo_configuration_and_read_only_connection_test(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeNameSiloClient:
        def __init__(self, api_key: str, *, payment_id: str | None = None) -> None:
            calls.append((api_key, payment_id))

        def verify_connection(self) -> None:
            calls.append(("verified", None))

        def get_account_balance(self) -> Decimal:
            calls.append(("balance", None))
            return Decimal("42.37")

        def close(self) -> None:
            calls.append(("closed", None))

    monkeypatch.setattr(configuration_router, "NameSiloClient", FakeNameSiloClient)
    secret = "namesilo-production-key-123456"
    admin_client.delete("/api/system/configuration/namesilo")
    try:
        saved = admin_client.put(
            "/api/system/configuration/namesilo",
            json={
                "value": secret,
                "enabled": True,
                "paymentMode": "account_balance",
                "paymentId": "2531590",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["platform"]["name"] == "NameSilo"
        assert saved.json()["data"]["platform"]["settings"]["paymentId"] == "2531590"
        assert saved.json()["data"]["platform"]["settings"]["paymentMode"] == "account_balance"

        tested = admin_client.post("/api/system/configuration/namesilo/test")
        assert tested.status_code == 200
        assert tested.json()["data"]["ok"] is True
        assert tested.json()["data"]["platform"]["lastTestStatus"] == "success"
        assert "账户余额 USD 42.37" in tested.json()["data"]["message"]
        assert calls == [
            (secret, None),
            ("verified", None),
            ("balance", None),
            ("closed", None),
        ]

        changed = admin_client.put(
            "/api/system/configuration/namesilo",
            json={"paymentMode": "verified_card", "paymentId": "2531591"},
        )
        assert changed.status_code == 200
        assert changed.json()["data"]["platform"]["settings"]["paymentId"] == "2531591"
        assert changed.json()["data"]["platform"]["lastTestStatus"] == "untested"

        tested_card = admin_client.post("/api/system/configuration/namesilo/test")
        assert tested_card.status_code == 200
        assert "实际购买时" in tested_card.json()["data"]["message"]
        assert calls[-3:] == [
            (secret, "2531591"),
            ("verified", None),
            ("closed", None),
        ]
    finally:
        admin_client.delete("/api/system/configuration/namesilo")


def test_namesilo_balance_mode_does_not_require_payment_id(admin_client: TestClient) -> None:
    admin_client.delete("/api/system/configuration/namesilo")
    try:
        response = admin_client.put(
            "/api/system/configuration/namesilo",
            json={
                "value": "namesilo-production-key-123456",
                "enabled": True,
                "paymentMode": "account_balance",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["platform"]["settings"]["paymentMode"] == "account_balance"
    finally:
        admin_client.delete("/api/system/configuration/namesilo")


def test_namesilo_verified_card_requires_payment_id(admin_client: TestClient) -> None:
    admin_client.delete("/api/system/configuration/namesilo")
    try:
        response = admin_client.put(
            "/api/system/configuration/namesilo",
            json={
                "value": "namesilo-production-key-123456",
                "enabled": True,
                "paymentMode": "verified_card",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == (
            "使用已验证信用卡支付时必须填写 NameSilo Payment ID"
        )
    finally:
        admin_client.delete("/api/system/configuration/namesilo")


def test_cloudflare_test_discovers_and_saves_single_account(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    class FakeCloudflareClient:
        def __init__(self, _token: str) -> None:
            pass

        def verify_connection(self) -> list[dict[str, str]]:
            return [{"id": "cf-account-1", "name": "Parloq"}]

        def close(self) -> None:
            pass

    monkeypatch.setattr(configuration_router, "CloudflareClient", FakeCloudflareClient)
    admin_client.delete("/api/system/configuration/cloudflare")
    try:
        assert admin_client.put(
            "/api/system/configuration/cloudflare",
            json={"value": "cloudflare-token-123456", "enabled": True},
        ).status_code == 200
        tested = admin_client.post("/api/system/configuration/cloudflare/test")
        assert tested.status_code == 200
        assert tested.json()["data"]["accounts"] == [
            {"id": "cf-account-1", "name": "Parloq"}
        ]
        assert tested.json()["data"]["platform"]["settings"]["accountId"] == "cf-account-1"
    finally:
        admin_client.delete("/api/system/configuration/cloudflare")


def test_baota_connection_test_uses_saved_panel_address(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeBaoTaClient:
        def __init__(self, base_url: str, _api_key: str) -> None:
            calls.append(base_url)

        def verify_connection(self) -> None:
            calls.append("verified")

        def nginx_firewall_plugin_available(self) -> bool:
            calls.append("firewall-probed")
            return False

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(configuration_router, "BaoTaClient", FakeBaoTaClient)
    admin_client.delete("/api/system/configuration/baota")
    try:
        assert admin_client.put(
            "/api/system/configuration/baota",
            json={
                "value": "baota-api-key-123456",
                "enabled": True,
                "baseUrl": "https://panel.example.com:8888",
            },
        ).status_code == 200
        tested = admin_client.post("/api/system/configuration/baota/test")
        assert tested.status_code == 200
        assert tested.json()["data"]["ok"] is True
        platform = tested.json()["data"]["platform"]
        assert platform["lastTestStatus"] == "success"
        assert platform["settings"]["nginxFirewallPlugin"]["status"] == "unavailable"
        assert "自动跳过" in tested.json()["data"]["message"]
        assert calls == [
            "https://panel.example.com:8888",
            "verified",
            "firewall-probed",
            "closed",
        ]

        policy = admin_client.put(
            "/api/system/configuration/baota",
            json={
                "firewallCdnEnabled": True,
                "firewallCcEnabled": False,
                "firewallChinaBlocked": True,
            },
        )
        assert policy.status_code == 200
        saved_platform = policy.json()["data"]["platform"]
        assert saved_platform["lastTestStatus"] == "success"
        assert saved_platform["settings"]["domainPolicy"] == {
            "cdnEnabled": True,
            "ccEnabled": False,
            "chinaBlocked": True,
        }
    finally:
        admin_client.delete("/api/system/configuration/baota")


def test_github_repository_configuration_and_read_only_connection_test(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    calls: list[object] = []

    class FakeGitHubRepositoryClient:
        def __init__(
            self,
            token: str,
            *,
            repository: str,
            ref: str,
            catalog_path: str,
        ) -> None:
            calls.append((token, repository, ref, catalog_path))

        def verify_connection(self) -> dict[str, str]:
            calls.append("verified")
            return {
                "repository": "zaptel099/parloq-flow-template-kit",
                "defaultBranch": "main",
            }

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(
        configuration_router,
        "GitHubRepositoryClient",
        FakeGitHubRepositoryClient,
    )
    admin_client.delete("/api/system/configuration/github")
    try:
        saved = admin_client.put(
            "/api/system/configuration/github",
            json={
                "value": "github-fine-grained-token-123456",
                "enabled": True,
                "repository": "https://github.com/zaptel099/parloq-flow-template-kit.git",
                "ref": "main",
                "catalogPath": "artifacts/catalog.json",
            },
        )
        assert saved.status_code == 200, saved.text
        platform = saved.json()["data"]["platform"]
        assert platform["settings"] == {
            "repository": "zaptel099/parloq-flow-template-kit",
            "ref": "main",
            "catalogPath": "artifacts/catalog.json",
        }
        tested = admin_client.post("/api/system/configuration/github/test")
        assert tested.status_code == 200, tested.text
        assert tested.json()["data"]["ok"] is True
        assert "zaptel099/parloq-flow-template-kit" in tested.json()["data"]["message"]
        assert calls == [
            (
                "github-fine-grained-token-123456",
                "zaptel099/parloq-flow-template-kit",
                "main",
                "artifacts/catalog.json",
            ),
            "verified",
            "closed",
        ]
    finally:
        admin_client.delete("/api/system/configuration/github")


def test_platform_credentials_are_admin_only(admin_client: TestClient) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator_group = next(row for row in groups if row["systemKey"] == "operator")
    username = f"credential-operator-{uuid4().hex[:8]}"
    password = "secure-pass-123"
    created = admin_client.post(
        "/api/users",
        json={
            "username": username,
            "password": password,
            "groupId": operator_group["id"],
        },
    )
    assert created.status_code == 201
    operator = TestClient(app)
    try:
        assert operator.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        ).status_code == 200
        assert operator.get("/api/system/configuration").status_code == 403
        assert operator.put(
            "/api/system/configuration/cloudflare",
            json={"value": "operator-must-not-save-this"},
        ).status_code == 403
        assert operator.post(
            "/api/system/configuration/cloudflare/test"
        ).status_code == 403
    finally:
        operator.close()
