from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.entity_ids import entity_id
from app.models import DomainRecord, UserAccount
from app.services import domain_onboarding
from app.snowflake import new_public_id


def test_purchased_domain_onboarding_advances_all_platforms_idempotently(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeCloudflareClient:
        def __init__(self, token: str, *, account_id: str) -> None:
            calls.append(("cloudflare", token, account_id))

        def find_zone(self, domain: str) -> dict[str, object]:
            calls.append(("find_zone", domain))
            return {
                "id": "zone-1",
                "name": domain,
                "status": "active",
                "name_servers": [
                    "elsa.ns.cloudflare.com",
                    "ray.ns.cloudflare.com",
                ],
            }

        def create_zone(self, _domain: str) -> dict[str, object]:
            raise AssertionError("existing zone must not be recreated")

        def ensure_dns_record(self, zone_id: str, **values: object) -> None:
            calls.append(("dns", zone_id, values))

        def ensure_zone_setting(self, zone_id: str, setting: str, value: object) -> None:
            calls.append(("setting", zone_id, setting, value))

        def close(self) -> None:
            calls.append(("close_cloudflare",))

    class FakeNameSiloClient:
        def __init__(self, token: str, *, payment_id: str | None) -> None:
            calls.append(("namesilo", token, payment_id))

        def owns_domain(self, domain: str) -> bool:
            calls.append(("owns_domain", domain))
            return True

        def get_domain_info(self, domain: str) -> dict[str, object]:
            calls.append(("domain_info", domain))
            return {"nameservers": ["old-one.example", "old-two.example"]}

        def change_name_servers(self, domain: str, nameservers: list[str]) -> None:
            calls.append(("change_nameservers", domain, tuple(nameservers)))

        def close(self) -> None:
            calls.append(("close_namesilo",))

    class FakeBaoTaClient:
        def __init__(self, base_url: str, token: str) -> None:
            calls.append(("baota", base_url, token))

        def find_site(self, domain: str) -> None:
            calls.append(("find_site", domain))
            return None

        def create_site(self, domain: str, path: str) -> dict[str, object]:
            calls.append(("create_site", domain, path))
            return {"id": 38, "name": domain, "path": path}

        def reverse_proxy_state(self, _domain: str, _upstream: str) -> str:
            raise AssertionError("a newly created site does not need adoption checks")

        def ensure_reverse_proxy(self, domain: str, upstream: str) -> None:
            calls.append(("proxy", domain, upstream))

        def close(self) -> None:
            calls.append(("close_baota",))

    platforms = {
        "cloudflare": domain_onboarding._Platform(
            secret="cf-token",
            settings={"accountId": "cf-account"},
        ),
        "namesilo": domain_onboarding._Platform(
            secret="namesilo-key",
            settings={"paymentMode": "verified_card", "paymentId": "2531590"},
        ),
        "baota": domain_onboarding._Platform(
            secret="baota-key",
            settings={"baseUrl": "https://panel.example"},
        ),
    }
    monkeypatch.setattr(
        domain_onboarding,
        "_platform",
        lambda _db, key, _credential_key: platforms[key],
    )
    monkeypatch.setattr(domain_onboarding, "CloudflareClient", FakeCloudflareClient)
    monkeypatch.setattr(domain_onboarding, "NameSiloClient", FakeNameSiloClient)
    monkeypatch.setattr(domain_onboarding, "BaoTaClient", FakeBaoTaClient)

    domain_id: str
    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        item = DomainRecord(
            public_id=new_public_id("dom"),
            hostname="automatic-purchase.example",
            acquisition_type="purchased",
            management_mode="platform",
            registrar_provider="namesilo",
            registration_status="active",
            hosting_provider="cloudflare",
            hosting_status="pending",
            verification_token="automatic-onboarding-proof",
            enabled=True,
            created_by=admin.id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        domain_id = entity_id(item)

        result = domain_onboarding.continue_domain_onboarding(db, item)
        assert result.onboarding_status == "completed"
        assert result.onboarding_stage == "completed"
        assert result.registration_status == "active"
        assert result.dns_status == "verified"
        assert result.ssl_status == "verified"
        assert result.hosting_status == "active"
        assert result.onboarding_state_json["cloudflareZoneId"] == "zone-1"
        assert result.onboarding_state_json["registrarNameserversUpdated"] is True
        assert result.onboarding_state_json["baotaSiteReady"] is True

    assert (
        "change_nameservers",
        "automatic-purchase.example",
        ("elsa.ns.cloudflare.com", "ray.ns.cloudflare.com"),
    ) in calls
    assert (
        "proxy",
        "automatic-purchase.example",
        "http://127.0.0.1:18100",
    ) in calls
    assert len([call for call in calls if call[0] == "dns"]) == 2
    assert len([call for call in calls if call[0] == "setting"]) == 2

    with SessionLocal() as db:
        item = db.get(DomainRecord, int(domain_id))
        assert item is not None
        db.delete(item)
        db.commit()


def test_external_domain_waits_for_nameserver_activation_without_baota(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    class PendingCloudflareClient:
        def __init__(self, _token: str, *, account_id: str) -> None:
            assert account_id == "cf-account"

        def find_zone(self, domain: str) -> dict[str, object]:
            return {
                "id": "zone-pending",
                "name": domain,
                "status": "pending",
                "name_servers": [
                    "elsa.ns.cloudflare.com",
                    "ray.ns.cloudflare.com",
                ],
            }

        def create_zone(self, _domain: str) -> dict[str, object]:
            raise AssertionError("existing zone must not be recreated")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        domain_onboarding,
        "_platform",
        lambda _db, key, _credential_key: domain_onboarding._Platform(
            secret="cf-token",
            settings={"accountId": "cf-account"},
        )
        if key == "cloudflare"
        else (_ for _ in ()).throw(AssertionError(f"unexpected platform {key}")),
    )
    monkeypatch.setattr(domain_onboarding, "CloudflareClient", PendingCloudflareClient)
    monkeypatch.setattr(
        domain_onboarding,
        "BaoTaClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("BaoTa must wait until Cloudflare is active")
        ),
    )

    domain_id: str
    with SessionLocal() as db:
        admin = db.scalar(select(UserAccount).where(UserAccount.username == "admin"))
        assert admin is not None
        item = DomainRecord(
            public_id=new_public_id("dom"),
            hostname="external-nameservers.example",
            acquisition_type="connected",
            management_mode="external",
            registration_status="pending",
            hosting_provider="cloudflare",
            hosting_status="pending",
            verification_token="external-nameserver-proof",
            enabled=True,
            created_by=admin.id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        domain_id = entity_id(item)

        result = domain_onboarding.continue_domain_onboarding(db, item)
        assert result.onboarding_status == "waiting"
        assert result.onboarding_stage == "registrar_nameservers"
        assert "请在域名注册商处改用" in (result.onboarding_message or "")
        assert result.onboarding_state_json["cloudflareNameservers"] == [
            "elsa.ns.cloudflare.com",
            "ray.ns.cloudflare.com",
        ]

    with SessionLocal() as db:
        item = db.get(DomainRecord, int(domain_id))
        assert item is not None
        db.delete(item)
        db.commit()
