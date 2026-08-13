from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BitlyProviderAccount


def test_mock_direct_bitly_link_lifecycle(admin_client: TestClient) -> None:
    accounts = admin_client.get("/api/direct-short-links/accounts")
    assert accounts.status_code == 200
    account = accounts.json()["data"]["rows"][0]
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
    assert link["shortUrl"].startswith("https://bit.ly/")
    assert link["targetUrl"].startswith("https://example.com/landing")

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
        json={"name": "Mock Secondary", "accessToken": "top-secret-bitly-token"},
    )
    assert response.status_code == 201
    serialized = response.json()["data"]["account"]
    assert serialized["tokenMasked"] == "••••oken"
    assert "top-secret" not in response.text

    with SessionLocal() as db:
        account = db.scalar(
            select(BitlyProviderAccount).where(BitlyProviderAccount.name == "Mock Secondary")
        )
        assert account is not None
        assert "top-secret-bitly-token" not in account.token_ciphertext
