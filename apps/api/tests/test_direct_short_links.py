from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BitlyProviderAccount
from app.security import secret_fingerprint
from app.services.bitly import BitlyServiceError


def test_mock_direct_bitly_link_lifecycle(admin_client: TestClient) -> None:
    accounts = admin_client.get("/api/direct-short-links/accounts")
    assert accounts.status_code == 200
    account = accounts.json()["data"]["rows"][0]
    assert account["id"].isdecimal()
    assert "publicId" not in account
    assert account["isMock"] is True
    assert "token" not in account

    created = admin_client.post(
        "/api/direct-short-links",
        json={
            "targetUrl": "https://example.com/landing?campaign=one",
            "title": "Campaign One",
            "providerAccountId": account["id"],
        },
    )
    assert created.status_code == 201
    link = created.json()["data"]["link"]
    assert link["id"].isdecimal()
    assert "publicId" not in link
    assert link["providerAccountId"] == account["id"]
    assert "providerAccountPublicId" not in link
    assert link["shortUrl"].startswith("https://bit.ly/")
    assert link["targetUrl"].startswith("https://example.com/landing")
    assert link["clickCount"] == 0
    assert link["clicksSyncedAt"] is None

    synced = admin_client.post(
        "/api/direct-short-links/sync-clicks",
        json={"linkIds": [link["id"]]},
    )
    assert synced.status_code == 200
    assert synced.json()["data"] == {
        "updated": 1,
        "failed": 0,
        "failures": [],
    }
    refreshed = admin_client.get("/api/direct-short-links").json()["data"]["rows"][0]
    assert refreshed["clickCount"] == 0
    assert refreshed["clicksSyncedAt"] is not None

    disabled = admin_client.patch(
        f"/api/direct-short-links/{link['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["link"]["status"] == "disabled"

    assert admin_client.delete(f"/api/direct-short-links/{link['id']}").status_code == 200
    assert admin_client.get("/api/direct-short-links").json()["data"]["total"] == 0


def test_bitly_token_is_encrypted_and_never_returned(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/bitly-accounts",
        json={"accessToken": "top-secret-bitly-token"},
    )
    assert response.status_code == 201
    serialized = response.json()["data"]["account"]
    assert serialized["id"].isdecimal()
    assert "publicId" not in serialized
    assert serialized["tokenMasked"] == "••••oken"
    assert serialized["name"].startswith("Bitly 本地模拟账号")
    assert serialized["groupGuid"] == "mock_group"
    assert serialized["shortDomain"] == "bit.ly"
    assert "top-secret" not in response.text

    with SessionLocal() as db:
        account = db.scalar(
            select(BitlyProviderAccount).where(
                BitlyProviderAccount.token_fingerprint
                == secret_fingerprint("top-secret-bitly-token")
            )
        )
        assert account is not None
        assert "top-secret-bitly-token" not in account.token_ciphertext


def test_automatic_account_selection_fails_over(
    admin_client: TestClient,
    monkeypatch,
) -> None:
    extra = admin_client.post(
        "/api/bitly-accounts",
        json={"accessToken": "failover-secondary-token"},
    )
    assert extra.status_code == 201

    with SessionLocal() as db:
        accounts = list(
            db.scalars(select(BitlyProviderAccount).order_by(BitlyProviderAccount.id)).all()
        )
        assert len(accounts) >= 2
        for account in accounts:
            account.enabled = True
            account.status = "active"
            account.cooldown_until = None
            account.last_used_at = None
        db.commit()
        first_account_id = accounts[0].id
        first_account_public_id = str(accounts[0].id)

    class FakeClient:
        def __init__(self, account_id: int) -> None:
            self.account_id = account_id

        def create_bitlink(self, **_kwargs):
            if self.account_id == first_account_id:
                raise BitlyServiceError(
                    "temporary failure",
                    category="temporary",
                )
            return {
                "id": f"bit.ly/{self.account_id}",
                "link": f"https://bit.ly/{self.account_id}",
            }

    monkeypatch.setattr(
        "app.routers.direct_short_links._client",
        lambda account: FakeClient(account.id),
    )
    created = admin_client.post(
        "/api/direct-short-links",
        json={"targetUrl": "https://example.com/failover"},
    )
    assert created.status_code == 201
    link = created.json()["data"]["link"]
    assert link["providerAccountId"] != first_account_public_id

    with SessionLocal() as db:
        first = db.get(BitlyProviderAccount, first_account_id)
        selected = db.get(BitlyProviderAccount, int(link["providerAccountId"]))
        assert first is not None and first.cooldown_until is not None
        assert first.status == "active"
        assert selected is not None and selected.last_used_at is not None

    assert admin_client.delete(f"/api/direct-short-links/{link['id']}").status_code == 200
