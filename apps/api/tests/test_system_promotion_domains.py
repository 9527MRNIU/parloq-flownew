from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import DomainOrder, DomainQuote, DomainRecord, UserAccount
from app.routers import domains as domains_router
from app.security import utcnow
from app.services.domain_registrar import DomainRegistrarError, MockDomainRegistrar
from app.snowflake import new_public_id


def _template_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html><head></head><body>promotion</body></html>")
    return output.getvalue()


def _account_group(admin_client: TestClient, name: str) -> str:
    response = admin_client.post("/api/account-groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["data"]["group"]["id"]


def test_external_domain_inventories_and_namesilo_purchase_source(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    class FakeCloudflareClient:
        def __init__(self, _token: str, *, account_id: str | None = None) -> None:
            assert account_id == "account-1"

        def list_zones(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "cloudflare-owned.example",
                    "status": "active",
                    "type": "full",
                    "account": {"name": "Primary"},
                    "name_servers": ["one.ns.cloudflare.com", "two.ns.cloudflare.com"],
                    "created_on": "2026-01-01T00:00:00Z",
                    "modified_on": "2026-02-01T00:00:00Z",
                }
            ]

        def close(self) -> None:
            pass

    class FakeNameSiloClient:
        def __init__(self, _key: str) -> None:
            pass

        def list_domains(self) -> list[dict[str, str]]:
            return [
                {
                    "domain": "system-bought.example",
                    "created": "2026-01-01",
                    "expires": "2027-01-01",
                },
                {
                    "domain": "account-existing.example",
                    "created": "2025-01-01",
                    "expires": "2027-02-01",
                },
            ]

        def close(self) -> None:
            pass

    monkeypatch.setattr(domains_router, "CloudflareClient", FakeCloudflareClient)
    monkeypatch.setattr(domains_router, "NameSiloClient", FakeNameSiloClient)

    admin_client.delete("/api/system/configuration/cloudflare")
    admin_client.delete("/api/system/configuration/namesilo")
    try:
        assert admin_client.put(
            "/api/system/configuration/cloudflare",
            json={
                "value": "cloudflare-account-token-123456",
                "enabled": True,
                "accountId": "account-1",
            },
        ).status_code == 200
        assert admin_client.put(
            "/api/system/configuration/namesilo",
            json={
                "value": "namesilo-api-key-123456",
                "enabled": True,
                "paymentId": "2531590",
            },
        ).status_code == 200

        with SessionLocal() as db:
            admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
            assert admin is not None
            quote = DomainQuote(
                public_id=new_public_id("dquote"),
                hostname="system-bought.example",
                years=1,
                amount=12,
                currency="USD",
                provider="namesilo",
                expires_at=utcnow() + timedelta(minutes=15),
                consumed_at=utcnow(),
                created_by=admin.id,
            )
            domain = DomainRecord(
                public_id=new_public_id("dom"),
                hostname="system-bought.example",
                acquisition_type="purchased",
                management_mode="platform",
                registrar_provider="namesilo",
                registration_status="active",
                hosting_provider="cloudflare",
                hosting_status="pending",
                verification_token="external-inventory-test-token",
                created_by=admin.id,
            )
            db.add_all([quote, domain])
            db.flush()
            order = DomainOrder(
                public_id=new_public_id("dord"),
                quote_id=quote.id,
                hostname=quote.hostname,
                years=1,
                amount=12,
                currency="USD",
                status="completed",
                provider="namesilo",
                provider_order_ref="namesilo:system-bought.example",
                domain_id=domain.id,
                completed_at=utcnow(),
                created_by=admin.id,
            )
            db.add(order)
            db.commit()

        cloudflare = admin_client.get("/api/domains/cloudflare")
        assert cloudflare.status_code == 200, cloudflare.text
        assert cloudflare.json()["data"]["rows"][0]["hostname"] == "cloudflare-owned.example"

        namesilo = admin_client.get("/api/domains/namesilo")
        assert namesilo.status_code == 200, namesilo.text
        rows = {row["hostname"]: row for row in namesilo.json()["data"]["rows"]}
        assert rows["system-bought.example"]["source"] == "system_purchase"
        assert rows["system-bought.example"]["order"]["status"] == "completed"
        assert rows["account-existing.example"]["source"] == "account_existing"
        assert rows["account-existing.example"]["order"] is None
    finally:
        admin_client.delete("/api/system/configuration/cloudflare")
        admin_client.delete("/api/system/configuration/namesilo")
        with SessionLocal() as db:
            order = db.scalar(
                select(DomainOrder).where(DomainOrder.hostname == "system-bought.example")
            )
            quote = db.scalar(
                select(DomainQuote).where(DomainQuote.hostname == "system-bought.example")
            )
            domain = db.scalar(
                select(DomainRecord).where(DomainRecord.hostname == "system-bought.example")
            )
            if order is not None:
                db.delete(order)
            if domain is not None:
                db.delete(domain)
            if quote is not None:
                db.delete(quote)
            db.commit()


def test_system_roles_menus_and_backend_permission(admin_client: TestClient) -> None:
    menus = admin_client.get("/api/system/menus")
    assert menus.status_code == 200
    rows = menus.json()["data"]["rows"]
    assert rows and all(row["id"].isdecimal() for row in rows)
    assert all("publicId" not in row for row in rows)
    by_route = {row["routePath"]: row for row in rows if row["routePath"]}
    assert by_route["/promotion/statistics"]["name"] == "渠道统计"
    assert by_route["/promotion/trends"]["name"] == "趋势图"
    assert "/personal-accounts" not in by_route
    assert "/resources/accounts/import" in by_route
    assert "/resources/accounts/export" in by_route
    assert "/resources/accounts/manage" in by_route
    assert "/resources/accounts/groups" in by_route
    assert "/resources/accounts/statistics" in by_route
    assert "/hyperlink/tasks" in by_route
    assert "/group-marketing/blast/tasks" in by_route
    assert "/group-marketing/market-analysis" in by_route
    assert "/resources/operations/protocol" in by_route
    assert "/resources/operations/ip" in by_route
    assert by_route["/promotion/domains"]["permissionKey"] == "promotion.domain.read"

    promotion_management = next(
        row for row in rows if row["name"] == "推广管理"
    )
    assert admin_client.patch(
        f"/api/system/menus/{promotion_management['id']}", json={"visible": False}
    ).status_code == 200
    hidden_tree = admin_client.get("/api/system/menus/me").json()["data"]["tree"]
    promotion_root = next(
        row for row in hidden_tree if row["name"] == "推广"
    )
    assert all(
        child["name"] != "推广管理"
        for child in promotion_root["children"]
    )
    assert not any(
        child["routePath"] == "/promotion/templates"
        for child in promotion_root["children"]
    )
    assert admin_client.patch(
        f"/api/system/menus/{promotion_management['id']}", json={"visible": True}
    ).status_code == 200

    templates_menu = by_route["/promotion/templates"]
    role = admin_client.post(
        "/api/system/roles",
        json={"name": "模板只读角色", "menuIds": [templates_menu["id"]]},
    )
    assert role.status_code == 201, role.text
    role_data = role.json()["data"]["role"]
    assert templates_menu["id"] in role_data["menuIds"]
    created = admin_client.post(
        "/api/users",
        json={
            "username": "template-role-user",
            "password": "template-role-pass",
            "roleId": role_data["id"],
        },
    )
    assert created.status_code == 201, created.text
    operator = TestClient(app)
    try:
        assert operator.post(
            "/api/auth/login",
            json={"username": "template-role-user", "password": "template-role-pass"},
        ).status_code == 200
        mine = operator.get("/api/system/menus/me")
        assert mine.status_code == 200
        assert "promotion.templates.read" in mine.json()["data"]["permissions"]
        assert operator.get("/api/promotion/templates").status_code == 200
        assert operator.post(
            "/api/promotion/templates",
            data={"name": "Denied write"},
            files={"file": ("denied.zip", _template_zip(), "application/zip")},
        ).status_code == 403
        assert operator.get("/api/promotion/channels").status_code == 403
        permission_change = admin_client.patch(
            f"/api/system/roles/{role_data['id']}", json={"menuIds": []}
        )
        assert permission_change.status_code == 200
        assert operator.get("/api/auth/me").status_code == 401
    finally:
        operator.close()


def test_domain_quote_order_unknown_reconcile_and_channel_options(
    admin_client: TestClient,
) -> None:
    quote = admin_client.post(
        "/api/domain-orders/quote", json={"hostname": "managed-flow.example", "years": 2}
    )
    assert quote.status_code == 201, quote.text
    quote_data = quote.json()["data"]["quote"]
    assert quote_data["id"].isdecimal()
    assert quote_data["quoteId"] == quote_data["id"]
    order = admin_client.post(
        "/api/domain-orders", json={"quoteId": quote_data["quoteId"], "autoRenew": True}
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["data"]["order"]["id"]
    assert order_id.isdecimal()
    assert order.json()["data"]["order"]["quoteId"] == quote_data["id"]
    assert admin_client.post(f"/api/domain-orders/{order_id}/mock-payment").status_code == 200
    completed = admin_client.post(f"/api/domain-orders/{order_id}/provision")
    assert completed.status_code == 200, completed.text
    domain = completed.json()["data"]["domain"]
    assert domain["acquisitionType"] == "purchased"
    assert domain["registrationStatus"] == "active"
    assert domain["hostingStatus"] == "pending"
    assert domain["channelSelectable"] is False
    verified = admin_client.post(f"/api/domains/{domain['id']}/verify")
    assert verified.status_code == 200
    assert verified.json()["data"]["domain"]["channelSelectable"] is True
    options = admin_client.get("/api/domains/available-for-channels").json()["data"]
    assert any(row["id"] == domain["id"] for row in options["rows"])

    timeout_quote = admin_client.post(
        "/api/domain-orders/quote", json={"hostname": "timeout.example", "years": 1}
    ).json()["data"]["quote"]
    timeout_order = admin_client.post(
        "/api/domain-orders", json={"quoteId": timeout_quote["quoteId"]}
    ).json()["data"]["order"]
    admin_client.post(f"/api/domain-orders/{timeout_order['id']}/mock-payment")
    unknown = admin_client.post(f"/api/domain-orders/{timeout_order['id']}/provision")
    assert unknown.status_code == 202
    assert unknown.json()["data"]["order"]["status"] == "unknown"
    assert admin_client.post(
        f"/api/domain-orders/{timeout_order['id']}/provision"
    ).status_code == 409
    reconciled = admin_client.post(
        f"/api/domain-orders/{timeout_order['id']}/reconcile"
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["data"]["order"]["status"] == "completed"


def test_definitive_provider_rejection_can_be_safely_retried_once(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    quote = admin_client.post(
        "/api/domain-orders/quote",
        json={"hostname": "definitive-rejection.example", "years": 1},
    ).json()["data"]["quote"]
    order = admin_client.post(
        "/api/domain-orders", json={"quoteId": quote["quoteId"]}
    ).json()["data"]["order"]
    assert admin_client.post(
        f"/api/domain-orders/{order['id']}/mock-payment"
    ).status_code == 200

    class FailingOnceRegistrar(MockDomainRegistrar):
        attempts = 0

        def register(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise DomainRegistrarError("注册商明确拒绝了支付方式")
            return super().register(*args, **kwargs)

    registrar = FailingOnceRegistrar()
    monkeypatch.setattr(domains_router, "_registrar", lambda _db, provider=None: registrar)

    rejected = admin_client.post(f"/api/domain-orders/{order['id']}/provision")
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "注册商明确拒绝了支付方式"

    failed_row = next(
        row
        for row in admin_client.get("/api/domain-orders").json()["data"]["rows"]
        if row["id"] == order["id"]
    )
    assert failed_row["status"] == "failed"
    assert failed_row["allowedActions"]["provision"] is True
    with SessionLocal() as db:
        persisted_order = db.get(DomainOrder, int(order["id"]))
        assert persisted_order is not None
        assert persisted_order.provider_order_ref is None

    completed = admin_client.post(f"/api/domain-orders/{order['id']}/provision")
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["order"]["status"] == "completed"
    assert registrar.attempts == 2

    duplicate = admin_client.post(f"/api/domain-orders/{order['id']}/provision")
    assert duplicate.status_code == 409
    assert registrar.attempts == 2


def test_real_registrar_quote_creates_purchase_ready_order(
    admin_client: TestClient,
) -> None:
    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        quote = DomainQuote(
            public_id=new_public_id("dquote"),
            hostname="real-registrar-order.example",
            years=1,
            amount=1.88,
            currency="USD",
            provider="namesilo",
            expires_at=utcnow() + timedelta(minutes=15),
            created_by=admin.id,
        )
        db.add(quote)
        db.commit()
        quote_id = str(quote.id)

    response = admin_client.post(
        "/api/domain-orders",
        json={"quoteId": quote_id, "autoRenew": False},
    )
    assert response.status_code == 201, response.text
    order = response.json()["data"]["order"]
    assert order["quoteId"] == quote_id
    assert order["provider"] == "namesilo"
    assert order["status"] == "purchase_ready"
    assert order["allowedActions"]["provision"] is True
    assert order["allowedActions"]["mockPayment"] is False

    with SessionLocal() as db:
        stored_quote = db.get(DomainQuote, int(quote_id))
        assert stored_quote is not None
        assert stored_quote.consumed_at is not None


def test_domain_order_integrity_error_classification() -> None:
    class Diagnostic:
        constraint_name = "domain_orders_quote_id_key"

    class DatabaseError(Exception):
        diag = Diagnostic()

    duplicate = domains_router.IntegrityError(
        "INSERT INTO domain_orders",
        {},
        DatabaseError("duplicate key value violates unique constraint"),
    )
    unrelated = domains_router.IntegrityError(
        "INSERT INTO domain_orders",
        {},
        Exception("violates check constraint ck_domain_orders_status"),
    )

    assert domains_router._is_duplicate_quote_order_error(duplicate) is True
    assert domains_router._is_duplicate_quote_order_error(unrelated) is False


def test_domain_search_returns_suffix_options_before_quote(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/domain-orders/search",
        json={"label": "suffix-search", "years": 2},
    )
    assert response.status_code == 202, response.text
    search = response.json()["data"]["search"]
    assert search["status"] == "completed"
    assert search["label"] == "suffix-search"
    assert search["years"] == 2
    assert search["candidateCount"] == 5
    assert search["searchedCount"] == 5
    assert search["skippedCount"] == 0
    assert search["partial"] is False
    assert [option["domain"] for option in search["options"]] == [
        "suffix-search.xyz",
        "suffix-search.org",
        "suffix-search.com",
        "suffix-search.net",
        "suffix-search.io",
    ]
    assert search["options"][0] == {
        "domain": "suffix-search.xyz",
        "registrationPrice": 6.0,
        "renewalPrice": 3.0,
        "currency": "USD",
        "years": 2,
    }
    assert "ownerUserId" not in search

    invalid = admin_client.post(
        "/api/domain-orders/search",
        json={"label": "-invalid", "years": 1},
    )
    assert invalid.status_code == 422


def test_domain_manage_cannot_bypass_purchase_permission(
    admin_client: TestClient,
) -> None:
    domain_menu = next(
        row
        for row in admin_client.get("/api/system/menus").json()["data"]["rows"]
        if row["permissionKey"] == "promotion.domain.read"
    )
    role = admin_client.post(
        "/api/system/roles",
        json={
            "name": "域名管理但不可购买",
            "menuIds": [domain_menu["id"]],
            "permissionKeys": ["promotion.domain.manage"],
        },
    ).json()["data"]["role"]
    created = admin_client.post(
        "/api/users",
        json={
            "username": "domain-manager-no-purchase",
            "password": "domain-manager-pass",
            "roleId": role["id"],
        },
    )
    assert created.status_code == 201, created.text

    admin_quote = admin_client.post(
        "/api/domain-orders/quote",
        json={"hostname": "purchase-permission.example", "years": 1},
    ).json()["data"]["quote"]
    admin_order = admin_client.post(
        "/api/domain-orders", json={"quoteId": admin_quote["quoteId"]}
    ).json()["data"]["order"]

    manager = TestClient(app)
    try:
        assert manager.post(
            "/api/auth/login",
            json={
                "username": "domain-manager-no-purchase",
                "password": "domain-manager-pass",
            },
        ).status_code == 200
        assert manager.get("/api/domains").status_code == 200
        assert manager.post(
            "/api/domains", json={"hostname": "managed-only.example"}
        ).status_code == 201
        assert manager.post(
            "/api/domain-orders/quote",
            json={"hostname": "forbidden-purchase.example", "years": 1},
        ).status_code == 403
        assert manager.post(
            "/api/domain-orders/search",
            json={"label": "forbidden-purchase", "years": 1},
        ).status_code == 403
        assert manager.post(
            "/api/domain-orders", json={"quoteId": admin_quote["quoteId"]}
        ).status_code == 403
        assert manager.post(
            f"/api/domain-orders/{admin_order['id']}/mock-payment"
        ).status_code == 403
        assert manager.post(
            "/api/domains/orders/quote",
            json={"hostname": "removed-alias.example", "years": 1},
        ).status_code == 404
    finally:
        manager.close()


def test_stale_provisioning_reconciles_and_cannot_be_cancelled(
    admin_client: TestClient,
) -> None:
    quote = admin_client.post(
        "/api/domain-orders/quote",
        json={"hostname": "stale-provisioning.example", "years": 1},
    ).json()["data"]["quote"]
    order = admin_client.post(
        "/api/domain-orders", json={"quoteId": quote["quoteId"]}
    ).json()["data"]["order"]
    assert admin_client.post(
        f"/api/domain-orders/{order['id']}/mock-payment"
    ).status_code == 200
    with SessionLocal() as db:
        item = db.scalar(select(DomainOrder).where(DomainOrder.id == int(order["id"])))
        assert item is not None
        item.status = "provisioning"
        item.updated_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()

    stale_row = next(
        row
        for row in admin_client.get("/api/domain-orders").json()["data"]["rows"]
        if row["id"] == order["id"]
    )
    assert stale_row["allowedActions"]["reconcile"] is True
    assert admin_client.post(
        f"/api/domain-orders/{order['id']}/cancel"
    ).status_code == 409
    reconciled = admin_client.post(
        f"/api/domain-orders/{order['id']}/reconcile"
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["data"]["order"]["status"] == "completed"


def test_connected_domain_verification_requires_issued_txt_and_cname(
    admin_client: TestClient, monkeypatch
) -> None:
    created = admin_client.post(
        "/api/domains", json={"hostname": "ownership-check.example"}
    )
    assert created.status_code == 201
    domain = created.json()["data"]["domain"]
    assert domain["registrationStatus"] == "pending"
    assert domain["channelSelectable"] is False
    captured: dict = {}

    def verify(hostname: str, **kwargs) -> None:
        captured["hostname"] = hostname
        captured.update(kwargs)

    settings = domains_router.get_settings()
    monkeypatch.setattr(
        domains_router,
        "get_settings",
        lambda: replace(settings, domain_verify_mock=False),
    )
    monkeypatch.setattr(domains_router, "verify_public_domain", verify)
    verified = admin_client.post(f"/api/domains/{domain['id']}/verify")
    assert verified.status_code == 200
    assert captured["hostname"] == "ownership-check.example"
    assert captured["verification_name"] == "_parloq-verify.ownership-check.example"
    assert captured["verification_value"].startswith("parloq-verification=")
    assert captured["cname_target"] == settings.promotion_ingress_host
    assert captured["routing_probe_path"].startswith(
        "/api/domains/public-verification/"
    )
    assert verified.json()["data"]["domain"]["channelSelectable"] is True


def test_domain_onboarding_continuation_claims_and_returns_progress(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    created = admin_client.post(
        "/api/domains", json={"hostname": "automatic-onboarding.example"}
    )
    assert created.status_code == 201
    domain = created.json()["data"]["domain"]

    calls: list[str] = []

    def complete_onboarding(db, item: DomainRecord) -> DomainRecord:
        calls.append(item.hostname)
        assert item.onboarding_status == "running"
        assert item.onboarding_attempted_at is not None
        item.onboarding_status = "completed"
        item.onboarding_stage = "completed"
        item.onboarding_message = "域名已自动接入并通过公网验证"
        item.registration_status = "active"
        item.dns_status = "verified"
        item.ssl_status = "verified"
        item.hosting_status = "active"
        db.commit()
        db.refresh(item)
        return item

    monkeypatch.setattr(
        domains_router,
        "continue_domain_onboarding",
        complete_onboarding,
    )
    continued = admin_client.post(
        f"/api/domains/{domain['id']}/onboarding/continue"
    )
    assert continued.status_code == 200, continued.text
    result = continued.json()["data"]["domain"]
    assert calls == ["automatic-onboarding.example"]
    assert result["onboarding"]["status"] == "completed"
    assert result["onboarding"]["stage"] == "completed"
    assert result["channelSelectable"] is True

    repeated = admin_client.post(
        f"/api/domains/{domain['id']}/onboarding/continue"
    )
    assert repeated.status_code == 200
    assert calls == ["automatic-onboarding.example"]


def test_domain_onboarding_rejects_an_active_duplicate_run(
    admin_client: TestClient,
) -> None:
    domain = admin_client.post(
        "/api/domains", json={"hostname": "onboarding-lease.example"}
    ).json()["data"]["domain"]
    with SessionLocal() as db:
        item = db.get(DomainRecord, int(domain["id"]))
        assert item is not None
        item.onboarding_status = "running"
        item.onboarding_attempted_at = datetime.now(UTC)
        db.commit()

    active = admin_client.get(f"/api/domains/{domain['id']}")
    assert active.status_code == 200
    assert active.json()["data"]["domain"]["onboarding"]["canContinue"] is False

    duplicate = admin_client.post(
        f"/api/domains/{domain['id']}/onboarding/continue"
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "域名接入流程正在执行，请勿重复提交"


def test_connected_domain_exposes_host_scoped_routing_proof(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/domains", json={"hostname": "proof.example"}
    ).json()["data"]["domain"]
    token = created["connection"]["txt"]["value"].split("=", 1)[1]

    path = f"/api/domains/public-verification/{token}"
    proof = admin_client.get(path, headers={"Host": "proof.example"})
    assert proof.status_code == 200
    assert proof.json()["data"] == {
        "hostname": "proof.example",
        "proof": "parloq-domain-routing-v1",
    }
    assert admin_client.get(
        path, headers={"Host": "wrong.example"}
    ).status_code == 404


def test_promotion_data_center_aggregates_uv_costs_and_successes(
    admin_client: TestClient,
) -> None:
    account_group_id = _account_group(admin_client, "Analytics Landing Accounts")
    domain = admin_client.post(
        "/api/domains", json={"hostname": "analytics-promotion.example"}
    ).json()["data"]["domain"]
    admin_client.post(f"/api/domains/{domain['id']}/verify")
    imported = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Analytics Template"},
        files={"file": ("analytics.zip", _template_zip(), "application/zip")},
    )
    template = imported.json()["data"]["template"]
    channel = admin_client.post(
        "/api/promotion/channels",
        json={
            "name": "Analytics Channel",
            "countryCode": "US",
            "templatePublicId": template["id"],
            "domainPublicId": domain["id"],
            "accountGroupId": account_group_id,
            "slug": "analytics-channel",
            "status": "active",
        },
    )
    assert channel.status_code == 201, channel.text
    channel_data = channel.json()["data"]["channel"]
    public = admin_client.get("/api/public/promotion/channels/analytics-channel").json()["data"]
    assert admin_client.get(
        "/api/public/promotion/channels/analytics-channel",
        headers={"Host": "wrong-domain.example"},
    ).status_code == 404
    assert admin_client.get(
        "/api/public/promotion/channels/analytics-channel",
        headers={"Host": "analytics-promotion.example"},
    ).status_code == 200
    common = {"sessionToken": public["sessionToken"], "visitorId": "visitor-analytics-0001"}
    events = [
        {"eventType": "page_view", "idempotencyKey": "analytics-page-view-0001"},
        {"eventType": "page_view", "idempotencyKey": "analytics-page-view-0002"},
        {
            "eventType": "phone_submit",
            "idempotencyKey": "analytics-phone-submit-0001",
            "phone": "+12025550188",
            "countryCode": "DE",
        },
        {
            "eventType": "phone_submit",
            "idempotencyKey": "analytics-phone-submit-0002",
            "phone": "+12025550188",
            "countryCode": "DE",
        },
    ]
    for event in events:
        response = admin_client.post(
            "/api/public/promotion/channels/analytics-channel/events",
            json={**common, **event},
        )
        assert response.status_code == 200, response.text
    public_success = admin_client.post(
        "/api/public/promotion/channels/analytics-channel/events",
        json={
            **common,
            "eventType": "login_success",
            "idempotencyKey": "untrusted-success-0001",
        },
    )
    assert public_success.status_code == 422
    for event_type, suffix in (("login_success", "login"), ("pair_success", "pair")):
        body = json.dumps(
            {
                "promotionChannelId": channel_data["id"],
                "eventType": event_type,
                "idempotencyKey": f"analytics-internal-{suffix}-0001",
                "visitorId": common["visitorId"],
            },
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(
            b"pytest-promotion-success-secret", body, hashlib.sha256
        ).hexdigest()
        success = admin_client.post(
            "/api/internal/promotion/success-events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Parloq-Signature": f"sha256={signature}",
            },
        )
        assert success.status_code == 200, success.text
    metric = admin_client.post(
        "/api/promotion/ad-metrics",
        json={
            "date": public["serverTimestamp"][:10],
            "promotionChannelId": channel_data["id"],
            "spend": 80,
            "otherCost": 20,
            "impressions": 1000,
            "clicks": 100,
        },
    )
    assert metric.status_code == 201, metric.text
    result = admin_client.get(
        f"/api/promotion/data-center/channels?channelIds={channel_data['id']}"
    )
    assert result.status_code == 200, result.text
    row = result.json()["data"]["rows"][0]
    assert row["pageViews"] == 2
    assert row["countryCode"] == "US"
    assert row["uv"] == 1
    assert row["submissions"] == 2
    assert row["leads"] == 1
    assert row["successes"] == 1
    assert row["loginSuccess"] == 1
    assert row["pairSuccess"] == 1
    assert row["totalCost"] == 100.0
    assert row["requestRate"] == 1.0
    assert row["successRate"] == 1.0
    assert row["costPerSuccess"] == 80.0
    assert any(detail["adMetricId"] for detail in row["daily"])
    trends = admin_client.get(
        f"/api/promotion/data-center/trends?channelIds={channel_data['id']}"
    )
    assert trends.status_code == 200
    assert any(point["uv"] == 1 for point in trends.json()["data"]["series"])
    legacy_summary = admin_client.get(
        f"/api/promotion/ad-metrics/summary?promotionChannelId={channel_data['id']}"
    )
    assert legacy_summary.status_code == 200
    assert legacy_summary.json()["data"]["leads"] == 1
    assert legacy_summary.json()["data"]["deprecated"] is True
    assert admin_client.patch(
        f"/api/domains/{domain['id']}", json={"enabled": False}
    ).status_code == 200
    assert admin_client.get(
        "/api/public/promotion/channels/analytics-channel",
        headers={"Host": "analytics-promotion.example"},
    ).status_code == 404


def test_channel_slug_is_scoped_to_ready_host(
    admin_client: TestClient,
) -> None:
    account_group_id = _account_group(admin_client, "Host Scoped Landing Accounts")
    domains = []
    for hostname in ("same-slug-one.example", "same-slug-two.example"):
        domain = admin_client.post(
            "/api/domains", json={"hostname": hostname}
        ).json()["data"]["domain"]
        assert admin_client.post(f"/api/domains/{domain['id']}/verify").status_code == 200
        domains.append(domain)
    template = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Host scoped slug template"},
        files={"file": ("host-scoped.zip", _template_zip(), "application/zip")},
    ).json()["data"]["template"]
    created_ids = []
    for index, domain in enumerate(domains, start=1):
        response = admin_client.post(
            "/api/promotion/channels",
            json={
                "name": f"Same Slug {index}",
                "countryCode": "US",
                "templatePublicId": template["id"],
                "domainPublicId": domain["id"],
                "accountGroupId": account_group_id,
                "slug": "same-landing",
                "status": "active",
            },
        )
        assert response.status_code == 201, response.text
        created_ids.append(response.json()["data"]["channel"]["id"])

    first = admin_client.get(
        "/api/public/promotion/channels/same-landing",
        headers={"Host": domains[0]["hostname"]},
    )
    second = admin_client.get(
        "/api/public/promotion/channels/same-landing",
        headers={"Host": domains[1]["hostname"]},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["channel"]["id"] == created_ids[0]
    assert second.json()["data"]["channel"]["id"] == created_ids[1]
    assert admin_client.get(
        "/api/public/promotion/channels/same-landing"
    ).status_code == 409


def test_channel_subdomain_prefix_builds_and_routes_public_url(
    admin_client: TestClient,
) -> None:
    account_group_id = _account_group(admin_client, "Subdomain Landing Accounts")
    domain = admin_client.post(
        "/api/domains", json={"hostname": "subdomain-routing.example"}
    ).json()["data"]["domain"]
    assert admin_client.post(f"/api/domains/{domain['id']}/verify").status_code == 200
    template = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Subdomain routing template"},
        files={"file": ("subdomain.zip", _template_zip(), "application/zip")},
    ).json()["data"]["template"]

    root = admin_client.post(
        "/api/promotion/channels",
        json={
            "name": "Root channel",
            "countryCode": "US",
            "templatePublicId": template["id"],
            "domainPublicId": domain["id"],
            "accountGroupId": account_group_id,
            "slug": "shared-path",
            "status": "active",
        },
    )
    subdomain = admin_client.post(
        "/api/promotion/channels",
        json={
            "name": "CN subdomain channel",
            "countryCode": "CN",
            "templatePublicId": template["id"],
            "domainPublicId": domain["id"],
            "accountGroupId": account_group_id,
            "subdomainPrefix": "CN",
            "slug": "shared-path",
            "status": "active",
        },
    )
    assert root.status_code == subdomain.status_code == 201
    root_row = root.json()["data"]["channel"]
    subdomain_row = subdomain.json()["data"]["channel"]
    assert root_row["publicUrl"] == "https://subdomain-routing.example/shared-path"
    assert subdomain_row["subdomainPrefix"] == "cn"
    assert subdomain_row["hostname"] == "cn.subdomain-routing.example"
    assert subdomain_row["publicUrl"] == "https://cn.subdomain-routing.example/shared-path"

    root_public = admin_client.get(
        "/api/public/promotion/channels/shared-path",
        headers={"Host": "subdomain-routing.example"},
    )
    subdomain_public = admin_client.get(
        "/api/public/promotion/channels/shared-path",
        headers={"Host": "cn.subdomain-routing.example"},
    )
    assert root_public.status_code == subdomain_public.status_code == 200
    assert root_public.json()["data"]["channel"]["id"] == root_row["id"]
    assert subdomain_public.json()["data"]["channel"]["id"] == subdomain_row["id"]
    assert admin_client.get(
        "/api/public/promotion/channels/shared-path",
        headers={"Host": "unknown.subdomain-routing.example"},
    ).status_code == 404

    invalid = admin_client.post(
        "/api/promotion/channels",
        json={
            "name": "Invalid subdomain channel",
            "countryCode": "US",
            "templatePublicId": template["id"],
            "domainPublicId": domain["id"],
            "subdomainPrefix": "bad.prefix",
            "slug": "invalid-subdomain",
        },
    )
    assert invalid.status_code == 422


def test_authenticated_backend_preview_bypasses_unready_domain_without_public_bypass(
    admin_client: TestClient,
) -> None:
    account_group_id = _account_group(admin_client, "Preview Landing Accounts")
    domain = admin_client.post(
        "/api/domains", json={"hostname": "preview-disabled.example"}
    ).json()["data"]["domain"]
    assert admin_client.post(f"/api/domains/{domain['id']}/verify").status_code == 200
    template = admin_client.post(
        "/api/promotion/templates",
        data={"name": "Backend preview security template"},
        files={"file": ("preview.zip", _template_zip(), "application/zip")},
    ).json()["data"]["template"]
    channel = admin_client.post(
        "/api/promotion/channels",
        json={
            "name": "Backend Preview Security",
            "countryCode": "US",
            "templatePublicId": template["id"],
            "domainPublicId": domain["id"],
            "accountGroupId": account_group_id,
            "slug": "backend-preview-security",
            "status": "active",
        },
    )
    assert channel.status_code == 201, channel.text
    assert admin_client.patch(
        f"/api/domains/{domain['id']}", json={"enabled": False}
    ).status_code == 200

    # The same-origin backend window carries the control-plane session and may
    # preview over a local/LAN host even when the eventual campaign domain is
    # unavailable.
    preview = admin_client.get(
        "/api/public/promotion/channels/backend-preview-security/render",
        headers={"Host": "192.168.50.20:5173"},
    )
    assert preview.status_code == 200, preview.text
    assert "promotion-runtime-config" in preview.text
    proxied_preview = admin_client.get(
        "/api/public/promotion/channels/backend-preview-security/render",
        headers={"Host": "api:8000"},
    )
    assert proxied_preview.status_code == 200, proxied_preview.text
    fission_preview = admin_client.get(
        "/api/public/promotion/channels/backend-preview-security/fission/render",
        headers={"Host": "api:8000"},
    )
    assert fission_preview.status_code == 200
    assert '"trafficSource": "fission"' in fission_preview.text

    # An anonymous visitor cannot turn either the local preview URL or the
    # disabled campaign hostname into a domain-validation bypass.
    with TestClient(app) as public_client:
        local_public = public_client.get(
            "/api/public/promotion/channels/backend-preview-security/render",
            headers={"Host": "192.168.50.20:5173"},
        )
        domain_public = public_client.get(
            "/api/public/promotion/channels/backend-preview-security/render",
            headers={"Host": domain["hostname"]},
        )
    assert local_public.status_code == 404
    assert local_public.json()["detail"] == "推广域名不可用"
    assert domain_public.status_code == 404
    assert domain_public.json()["detail"] == "推广域名不可用"
