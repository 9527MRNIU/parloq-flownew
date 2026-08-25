from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AccountProxyBinding,
    IpAllocationPolicy,
    PersonalAccount,
    ProxyEndpoint,
    ProxyHealthEvent,
    UserAccount,
)
from app.routers.personal_accounts import _auto_proxy
from app.routers.ip_proxies import _reconcile_account_proxy_best_effort
from app.security import utcnow
from app.services.proxy_health import (
    ProxyHealthPolicy,
    ProxyProbeResult,
    apply_proxy_health_result,
    proxy_fingerprint,
)
from app.services.wa_gateway import GatewayError, WaGatewayClient
from app.snowflake import new_public_id


def _proxy_health_event(
    client: TestClient,
    *,
    event_id: str,
    account_id: str,
    outcome: str,
    reason: str,
    fingerprint: str,
):
    with SessionLocal() as db:
        account = db.get(PersonalAccount, int(account_id))
        assert account is not None
        gateway_account_id = account.gateway_account_id
    body = json.dumps(
        {
            "event": "proxy.health",
            "eventId": event_id,
            "accountId": gateway_account_id,
            "outcome": outcome,
            "reasonCategory": reason,
            "proxyFingerprint": fingerprint,
            "occurredAt": utcnow().isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"pytest-wa-webhook-secret", body, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/api/internal/wa-gateway/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Parloq-Signature": f"sha256={signature}",
        },
    )


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
            "countryMatch": "phone_country",
            "maxAccountsPerIp": 8,
            "avoidUnhealthy": True,
            "stickyBinding": True,
        },
    )
    assert updated_policy.status_code == 200
    assert updated_policy.json()["data"]["policy"]["countryMatch"] == "phone_country"
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
    assert binding_one["accountName"] == "Proxy account 61"
    assert binding_one["accountPhone"] == "+12025550061"
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


def test_batch_rebind_maps_each_source_proxy_to_manual_target(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    def create_proxy(name: str, host: str) -> dict:
        response = admin_client.post(
            "/api/ip-proxies",
            json={
                "name": name,
                "protocol": "http",
                "host": host,
                "port": 8080,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]["proxy"]

    source_one = create_proxy("Rebind source one", "rebind-source-one.test")
    source_two = create_proxy("Rebind source two", "rebind-source-two.test")
    target_one = create_proxy("Rebind target one", "rebind-target-one.test")
    target_two = create_proxy("Rebind target two", "rebind-target-two.test")
    account_one = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Manual rebind account one",
            "phone": "+12025551001",
            "proxyId": source_one["id"],
        },
    ).json()["data"]["account"]
    account_two = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Manual rebind account two",
            "phone": "+12025551002",
            "proxyId": source_two["id"],
        },
    ).json()["data"]["account"]

    disconnected: list[str] = []
    synchronized: list[tuple[str, str | None]] = []
    with SessionLocal() as db:
        stored_account = db.get(PersonalAccount, int(account_one["id"]))
        assert stored_account is not None
        stored_account.status = "online_idle"
        online_gateway_id = stored_account.gateway_account_id
        db.commit()

    def record_disconnect(self, account_id: str):
        disconnected.append(account_id)
        return {"id": account_id, "state": "linked_offline"}

    def record_update(self, account_id: str, proxy_url: str | None):
        synchronized.append((account_id, proxy_url))
        return {"id": account_id, "state": "linked_offline"}

    monkeypatch.setattr(WaGatewayClient, "disconnect", record_disconnect)
    monkeypatch.setattr(WaGatewayClient, "update_proxy", record_update)
    response = admin_client.post(
        "/api/ip-proxy-bindings/rebind-batch",
        json={
            "mode": "manual",
            "sourceProxyIds": [source_one["id"], source_two["id"]],
            "mappings": [
                {
                    "sourceProxyId": source_one["id"],
                    "targetProxyId": target_one["id"],
                },
                {
                    "sourceProxyId": source_two["id"],
                    "targetProxyId": target_two["id"],
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"] == {
        "sourceProxies": 2,
        "accounts": 2,
        "migrated": 2,
        "failed": 0,
        "emptySources": 0,
    }
    assert disconnected == [online_gateway_id]
    assert len(synchronized) == 2
    with SessionLocal() as db:
        bindings = {
            item.account_public_id: item.proxy_id
            for item in db.scalars(
                select(AccountProxyBinding).where(
                    AccountProxyBinding.account_public_id.in_(
                        [
                            db.get(PersonalAccount, int(account_one["id"])).gateway_account_id,
                            db.get(PersonalAccount, int(account_two["id"])).gateway_account_id,
                        ]
                    )
                )
            ).all()
        }
        assert set(bindings.values()) == {
            int(target_one["id"]),
            int(target_two["id"]),
        }

    assert admin_client.delete(
        f"/api/personal-accounts/{account_one['id']}"
    ).status_code == 200
    assert admin_client.delete(
        f"/api/personal-accounts/{account_two['id']}"
    ).status_code == 200
    for proxy in (source_one, source_two, target_one, target_two):
        assert admin_client.delete(
            f"/api/ip-proxies/{proxy['id']}"
        ).status_code == 200


def test_batch_rebind_automatic_excludes_sources_and_uses_allocation_policy(
    admin_client: TestClient,
) -> None:
    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        admin_id = admin.id
        existing_proxies = list(db.scalars(select(ProxyEndpoint)).all())
        existing_proxy_ids = [proxy.id for proxy in existing_proxies]
        previous_enabled = {proxy.id: proxy.enabled for proxy in existing_proxies}
        for proxy in existing_proxies:
            proxy.enabled = False
        policy = db.scalar(
            select(IpAllocationPolicy).where(
                IpAllocationPolicy.created_by == admin_id
            )
        )
        assert policy is not None
        previous_policy = (
            policy.allocation_mode,
            policy.country_match,
            policy.max_accounts_per_ip,
        )
        policy.allocation_mode = "least_load"
        policy.country_match = "phone_country"
        policy.max_accounts_per_ip = 100
        db.commit()

    def create_proxy(name: str, host: str, country_code: str) -> dict:
        response = admin_client.post(
            "/api/ip-proxies",
            json={
                "name": name,
                "protocol": "http",
                "host": host,
                "port": 8080,
                "countryCode": country_code,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]["proxy"]

    source_us = create_proxy("Automatic source US", "auto-source-us.test", "US")
    source_de = create_proxy("Automatic source DE", "auto-source-de.test", "DE")
    target_us = create_proxy("Automatic target US", "auto-target-us.test", "US")
    target_de = create_proxy("Automatic target DE", "auto-target-de.test", "DE")
    account_us = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Automatic rebind US",
            "phone": "+12025551003",
            "proxyId": source_us["id"],
        },
    ).json()["data"]["account"]
    account_de = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Automatic rebind DE",
            "phone": "+4915112345678",
            "proxyId": source_de["id"],
        },
    ).json()["data"]["account"]

    response = admin_client.post(
        "/api/ip-proxy-bindings/rebind-batch",
        json={
            "mode": "automatic",
            "sourceProxyIds": [source_us["id"], source_de["id"]],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["migrated"] == 2
    with SessionLocal() as db:
        us_binding = db.scalar(
            select(AccountProxyBinding).where(
                AccountProxyBinding.account_public_id
                == db.get(PersonalAccount, int(account_us["id"])).gateway_account_id
            )
        )
        de_binding = db.scalar(
            select(AccountProxyBinding).where(
                AccountProxyBinding.account_public_id
                == db.get(PersonalAccount, int(account_de["id"])).gateway_account_id
            )
        )
        assert us_binding is not None and us_binding.proxy_id == int(target_us["id"])
        assert de_binding is not None and de_binding.proxy_id == int(target_de["id"])

    assert admin_client.delete(
        f"/api/personal-accounts/{account_us['id']}"
    ).status_code == 200
    assert admin_client.delete(
        f"/api/personal-accounts/{account_de['id']}"
    ).status_code == 200
    for proxy in (source_us, source_de, target_us, target_de):
        assert admin_client.delete(
            f"/api/ip-proxies/{proxy['id']}"
        ).status_code == 200
    with SessionLocal() as db:
        for proxy_id in existing_proxy_ids:
            stored = db.get(ProxyEndpoint, proxy_id)
            if stored is not None:
                stored.enabled = previous_enabled[proxy_id]
        policy = db.scalar(
            select(IpAllocationPolicy).where(
                IpAllocationPolicy.created_by == admin_id
            )
        )
        assert policy is not None
        (
            policy.allocation_mode,
            policy.country_match,
            policy.max_accounts_per_ip,
        ) = previous_policy
        db.commit()


def test_orphaned_proxy_binding_can_be_deleted_by_binding_id(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Orphan binding cleanup proxy",
            "protocol": "http",
            "host": "orphan-binding.example.test",
            "port": 8080,
        },
    )
    assert created.status_code == 201, created.text
    proxy = created.json()["data"]["proxy"]

    with SessionLocal() as db:
        binding = AccountProxyBinding(
            public_id=new_public_id("ipb"),
            account_public_id=f"missing-{new_public_id('acct')}",
            proxy_id=int(proxy["id"]),
        )
        db.add(binding)
        db.flush()
        binding_id = str(binding.id)
        db.commit()

    listed = admin_client.get(
        "/api/ip-proxy-bindings",
        params={"proxyId": proxy["id"]},
    )
    assert listed.status_code == 200, listed.text
    row = listed.json()["data"]["rows"][0]
    assert row["id"] == binding_id
    assert "accountId" not in row

    deleted = admin_client.delete(f"/api/ip-proxy-bindings/{binding_id}")
    assert deleted.status_code == 200, deleted.text
    detail = admin_client.get(f"/api/ip-proxies/{proxy['id']}")
    assert detail.json()["data"]["proxy"]["assignedAccountCount"] == 0
    assert admin_client.delete(f"/api/ip-proxies/{proxy['id']}").status_code == 200


def test_proxy_unbind_succeeds_when_gateway_account_is_already_missing(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    account_response = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Missing gateway binding account", "phone": "+12025550064"},
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()["data"]["account"]
    if account["proxyBinding"] is not None:
        existing_binding_id = account["proxyBinding"]["bindingId"]
        assert admin_client.delete(
            f"/api/ip-proxy-bindings/{existing_binding_id}"
        ).status_code == 200

    proxy_response = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Missing gateway unbind proxy",
            "protocol": "socks5",
            "host": "missing-gateway-unbind.example.test",
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
    binding = binding_response.json()["data"]["binding"]

    calls: list[str] = []

    def missing_gateway_account(self, account_id, proxy_url):
        calls.append(account_id)
        raise GatewayError(
            "WhatsApp 网关请求失败（404）",
            status_code=404,
        )

    monkeypatch.setattr(WaGatewayClient, "update_proxy", missing_gateway_account)

    deleted = admin_client.delete(f"/api/ip-proxy-bindings/{binding['id']}")
    assert deleted.status_code == 200, deleted.text
    assert len(calls) == 1
    listed = admin_client.get(
        "/api/ip-proxy-bindings",
        params={"proxyId": proxy["id"]},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"]["rows"] == []


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


def test_detected_country_fills_only_an_empty_proxy_country() -> None:
    proxy = ProxyEndpoint(
        public_id=new_public_id("ipx"),
        name="Automatic country proxy",
        protocol="http",
        host="proxy-country.example.test",
        port=8080,
        enabled=True,
        health_status="untested",
    )
    policy = ProxyHealthPolicy()
    apply_proxy_health_result(
        proxy,
        ProxyProbeResult(healthy=True, country_code="BR"),
        source="import",
        policy=policy,
        direct_probe=True,
    )
    assert proxy.country_code == "BR"

    proxy.country_code = "US"
    apply_proxy_health_result(
        proxy,
        ProxyProbeResult(healthy=True, country_code="DE"),
        source="manual",
        policy=policy,
        direct_probe=True,
    )
    assert proxy.country_code == "US"


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

    first_check = admin_client.post(
        "/api/ip-proxies/test-batch",
        json={
            "proxyIds": [row["id"] for row in rows],
            "source": "import",
        },
    )
    assert first_check.status_code == 200, first_check.text
    assert first_check.json()["data"]["summary"] == {
        "total": 5,
        "healthy": 5,
        "unhealthy": 0,
    }
    assert {
        row["lastCheckSource"] for row in first_check.json()["data"]["rows"]
    } == {"import"}

    manual_check = admin_client.post(
        "/api/ip-proxies/test-batch",
        json={"proxyIds": [rows[0]["id"]]},
    )
    assert manual_check.status_code == 200, manual_check.text
    assert manual_check.json()["data"]["rows"][0]["lastCheckSource"] == "manual"

    duplicate = admin_client.post(
        "/api/ip-proxies/bulk",
        json={"lines": ["https://203.0.113.21:8080"]},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["summary"]["duplicate"] == 1
    assert duplicate.json()["data"]["rows"] == []


def test_two_stage_proxy_import_detects_before_writing_and_supports_both_modes(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    def probe(proxy: ProxyEndpoint) -> ProxyProbeResult:
        if proxy.host.endswith("32") or proxy.host.endswith("34"):
            return ProxyProbeResult(
                healthy=False,
                reason_category="proxy_connection_failed",
                error="代理无法访问 WhatsApp Web",
            )
        return ProxyProbeResult(
            healthy=True,
            latency_ms=84,
            country_code="DE",
        )

    monkeypatch.setattr("app.routers.ip_proxies.probe_proxy", probe)
    with SessionLocal() as db:
        before_count = int(db.scalar(select(func.count()).select_from(ProxyEndpoint)) or 0)

    request_body = {
        "lines": [
            "203.0.113.31:8031:preview-user:preview-password",
            "203.0.113.32:8032",
            "invalid-line",
        ],
        "defaultProtocol": "socks5",
        "provider": "Preview Provider",
    }
    preview = admin_client.post(
        "/api/ip-proxies/import-preview",
        json=request_body,
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()["data"]
    assert preview_data["summary"] == {
        "total": 3,
        "candidates": 2,
        "healthy": 1,
        "unhealthy": 1,
        "duplicate": 0,
        "failed": 1,
    }
    assert [item["status"] for item in preview_data["results"]] == [
        "checked",
        "checked",
        "failed",
    ]
    assert preview_data["results"][0]["countryCode"] == "DE"
    assert preview_data["results"][0]["latencyMs"] == 84
    assert "preview-user" not in preview.text
    assert "preview-password" not in preview.text
    with SessionLocal() as db:
        assert int(db.scalar(select(func.count()).select_from(ProxyEndpoint)) or 0) == before_count

    healthy_only = admin_client.post(
        "/api/ip-proxies/import-confirm",
        json={
            **request_body,
            "previewToken": preview_data["previewToken"],
            "importMode": "healthy",
        },
    )
    assert healthy_only.status_code == 201, healthy_only.text
    healthy_data = healthy_only.json()["data"]
    assert healthy_data["summary"] == {
        "total": 3,
        "created": 1,
        "skipped": 1,
        "duplicate": 0,
        "failed": 1,
    }
    assert healthy_data["rows"][0]["host"] == "203.0.113.31"
    assert healthy_data["rows"][0]["healthStatus"] == "healthy"
    assert healthy_data["rows"][0]["countryCode"] == "DE"
    assert healthy_data["rows"][0]["lastCheckSource"] == "import"

    all_body = {
        "lines": ["203.0.113.33:8033", "203.0.113.34:8034"],
        "defaultProtocol": "http",
    }
    all_preview = admin_client.post(
        "/api/ip-proxies/import-preview",
        json=all_body,
    )
    assert all_preview.status_code == 200, all_preview.text
    all_import = admin_client.post(
        "/api/ip-proxies/import-confirm",
        json={
            **all_body,
            "previewToken": all_preview.json()["data"]["previewToken"],
            "importMode": "all",
        },
    )
    assert all_import.status_code == 201, all_import.text
    assert all_import.json()["data"]["summary"]["created"] == 2
    imported_by_host = {
        row["host"]: row for row in all_import.json()["data"]["rows"]
    }
    assert imported_by_host["203.0.113.33"]["healthStatus"] == "healthy"
    assert imported_by_host["203.0.113.34"]["healthStatus"] == "unhealthy"
    assert imported_by_host["203.0.113.34"]["lastError"] == "代理无法访问 WhatsApp Web"


def test_proxy_import_preview_streams_each_completed_result(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    slow_probe_started = threading.Event()
    release_slow_probe = threading.Event()

    def probe(proxy: ProxyEndpoint) -> ProxyProbeResult:
        if proxy.host.endswith("51"):
            slow_probe_started.set()
            assert release_slow_probe.wait(timeout=2)
            time.sleep(0.05)
            return ProxyProbeResult(healthy=True, latency_ms=91, country_code="US")
        assert slow_probe_started.wait(timeout=2)
        release_slow_probe.set()
        return ProxyProbeResult(healthy=False, error="代理无法访问 WhatsApp Web")

    monkeypatch.setattr("app.routers.ip_proxies.probe_proxy", probe)
    body = {
        "requestId": "proxy-preview-stream-test",
        "lines": [
            "203.0.113.51:8051:stream-user:stream-password",
            "203.0.113.52:8052",
        ],
    }

    with admin_client.stream(
        "POST",
        "/api/ip-proxies/import-preview/stream",
        json=body,
    ) as response:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert response.headers["x-accel-buffering"] == "no"
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert [event["type"] for event in events] == [
        "snapshot",
        "result",
        "result",
        "complete",
    ]
    assert [item["status"] for item in events[0]["results"]] == [
        "checking",
        "checking",
    ]
    assert [event["result"]["line"] for event in events[1:3]] == [2, 1]
    assert events[1]["result"]["healthStatus"] == "unhealthy"
    assert events[2]["result"]["countryCode"] == "US"
    assert events[-1]["data"]["summary"]["healthy"] == 1
    assert events[-1]["data"]["summary"]["unhealthy"] == 1
    serialized = json.dumps(events)
    assert "stream-user" not in serialized
    assert "stream-password" not in serialized


def test_proxy_import_confirmation_rejects_changed_or_tampered_preview(
    admin_client: TestClient,
) -> None:
    request_body = {"lines": ["203.0.113.41:8041"]}
    preview = admin_client.post(
        "/api/ip-proxies/import-preview",
        json=request_body,
    )
    assert preview.status_code == 200, preview.text
    token = preview.json()["data"]["previewToken"]

    changed = admin_client.post(
        "/api/ip-proxies/import-confirm",
        json={
            "lines": ["203.0.113.41:9041"],
            "previewToken": token,
            "importMode": "all",
        },
    )
    assert changed.status_code == 409
    assert changed.json()["detail"] == "代理内容已变化，请重新检测"

    tampered = admin_client.post(
        "/api/ip-proxies/import-confirm",
        json={
            **request_body,
            "previewToken": token[:-1] + ("0" if token[-1] != "0" else "1"),
            "importMode": "all",
        },
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"] == "检测结果已失效，请重新检测"


def test_proxy_import_preview_can_cancel_queued_probes(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    probes_started = threading.Event()
    release_probes = threading.Event()
    call_lock = threading.Lock()
    probe_calls = 0

    def probe(_proxy: ProxyEndpoint) -> ProxyProbeResult:
        nonlocal probe_calls
        with call_lock:
            probe_calls += 1
            if probe_calls == 10:
                probes_started.set()
        assert release_probes.wait(timeout=3)
        return ProxyProbeResult(healthy=True)

    monkeypatch.setattr("app.routers.ip_proxies.probe_proxy", probe)
    request_id = "proxy-preview-cancel-test"
    body = {
        "requestId": request_id,
        "lines": [f"203.0.113.{index}:{8000 + index}" for index in range(1, 21)],
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        preview_future = executor.submit(
            admin_client.post,
            "/api/ip-proxies/import-preview",
            json=body,
        )
        assert probes_started.wait(timeout=3)
        cancelled = admin_client.post(
            f"/api/ip-proxies/import-preview/{request_id}/cancel",
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"] == {"ok": True, "cancelled": True}
        release_probes.set()
        preview = preview_future.result(timeout=5)

    assert preview.status_code == 409, preview.text
    assert preview.json()["detail"] == "代理检测已取消"
    assert probe_calls == 10


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
    assert admin_client.delete(f"/api/user-groups/{group_id}").status_code == 200


def test_gateway_proxy_failures_are_idempotent_and_enter_cooldown(
    admin_client: TestClient,
) -> None:
    policy = admin_client.patch(
        "/api/ip-allocation-policy",
        json={
            "allocationMode": "least_load",
            "countryMatch": "phone_country",
            "maxAccountsPerIp": 100,
            "avoidUnhealthy": True,
            "stickyBinding": True,
            "failureThreshold": 2,
            "cooldownSeconds": 600,
        },
    )
    assert policy.status_code == 200, policy.text
    created_proxy = admin_client.post(
        "/api/ip-proxies",
        json={
            "name": "Runtime health proxy",
            "protocol": "http",
            "host": "203.0.113.91",
            "port": 8091,
            "username": "runtime-user",
            "password": "runtime-password",
        },
    ).json()["data"]["proxy"]
    account_response = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Runtime health account",
            "phone": "+12025559876",
            "proxyId": created_proxy["id"],
        },
    )
    assert account_response.status_code == 201, account_response.text
    account_id = account_response.json()["data"]["account"]["id"]
    with SessionLocal() as db:
        proxy = db.get(ProxyEndpoint, int(created_proxy["id"]))
        assert proxy is not None
        fingerprint = proxy_fingerprint(proxy)

    first = _proxy_health_event(
        admin_client,
        event_id="phv_runtime_failure_1",
        account_id=account_id,
        outcome="failure",
        reason="proxy_connection_failed",
        fingerprint=fingerprint,
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["enteredCooldown"] is False
    second = _proxy_health_event(
        admin_client,
        event_id="phv_runtime_failure_2",
        account_id=account_id,
        outcome="failure",
        reason="proxy_connection_failed",
        fingerprint=fingerprint,
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["enteredCooldown"] is True
    duplicate = _proxy_health_event(
        admin_client,
        event_id="phv_runtime_failure_2",
        account_id=account_id,
        outcome="failure",
        reason="proxy_connection_failed",
        fingerprint=fingerprint,
    )
    assert duplicate.json()["data"]["duplicate"] is True

    with SessionLocal() as db:
        proxy = db.get(ProxyEndpoint, int(created_proxy["id"]))
        assert proxy is not None
        assert proxy.health_status == "unhealthy"
        assert proxy.consecutive_failures == 2
        assert proxy.cooldown_until is not None
        assert db.scalar(select(func.count()).select_from(ProxyHealthEvent)) >= 2

    recovered = _proxy_health_event(
        admin_client,
        event_id="phv_runtime_success",
        account_id=account_id,
        outcome="success",
        reason="proxy_connected",
        fingerprint=fingerprint,
    )
    assert recovered.status_code == 200, recovered.text
    with SessionLocal() as db:
        proxy = db.get(ProxyEndpoint, int(created_proxy["id"]))
        assert proxy is not None
        assert proxy.health_status == "healthy"
        assert proxy.consecutive_failures == 0
        assert proxy.cooldown_until is None


def test_allocation_uses_selected_country_source_and_skips_cooldown(
    admin_client: TestClient,
) -> None:
    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        existing = list(db.scalars(select(ProxyEndpoint)).all())
        previous_enabled = {item.id: item.enabled for item in existing}
        for item in existing:
            item.enabled = False
        us_proxy = ProxyEndpoint(
            public_id=new_public_id("ipx"),
            name="Phone country proxy",
            protocol="http",
            host="203.0.113.101",
            port=8101,
            enabled=True,
            health_status="healthy",
        )
        us_proxy.country_code = "US"
        de_proxy = ProxyEndpoint(
            public_id=new_public_id("ipx"),
            name="Visitor country proxy",
            protocol="http",
            host="203.0.113.102",
            port=8102,
            enabled=True,
            health_status="healthy",
        )
        de_proxy.country_code = "DE"
        db.add_all([us_proxy, de_proxy])
        policy = db.scalar(
            select(IpAllocationPolicy).where(
                IpAllocationPolicy.created_by == admin.id
            )
        )
        assert policy is not None
        policy.allocation_mode = "least_load"
        policy.country_match = "visitor_country"
        db.flush()
        assert _auto_proxy(db, admin.id, "US", "DE") is de_proxy
        policy.country_match = "phone_country"
        db.flush()
        assert _auto_proxy(db, admin.id, "US", "DE") is us_proxy
        us_proxy.cooldown_until = utcnow() + timedelta(minutes=5)
        us_proxy.health_status = "unhealthy"
        db.flush()
        assert _auto_proxy(db, admin.id, "US", "DE") is de_proxy
        db.delete(us_proxy)
        db.delete(de_proxy)
        for item in existing:
            item.enabled = previous_enabled[item.id]
        db.commit()
