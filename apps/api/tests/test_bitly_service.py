from __future__ import annotations

import httpx
import pytest
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.maintenance.import_waba_bitly import BitlyImportError, import_accounts
from app.models import BitlyProviderAccount
from app.security import decrypt_secret, secret_fingerprint
from app.services.bitly import BitlyClient, BitlyServiceError


def test_account_discovery_uses_default_group_and_domain_preference(monkeypatch) -> None:
    def fake_request(method: str, url: str, **_kwargs) -> httpx.Response:
        assert method == "GET"
        if url.endswith("/v4/user"):
            return httpx.Response(
                200,
                json={
                    "login": "owner@example.com",
                    "name": "Parloq Bitly",
                    "default_group_guid": "group-default",
                },
            )
        if url.endswith("/v4/groups"):
            return httpx.Response(
                200,
                json={
                    "groups": [
                        {
                            "guid": "group-other",
                            "name": "Other",
                            "bsds": ["other.example"],
                        },
                        {
                            "guid": "group-default",
                            "name": "Default",
                            "bsds": ["fallback.example"],
                        },
                    ]
                },
            )
        if url.endswith("/v4/groups/group-default/preferences"):
            return httpx.Response(
                200,
                json={
                    "group_guid": "group-default",
                    "domain_preference": "go.parloq.com",
                },
            )
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "request", fake_request)
    discovered = BitlyClient("secret").discover_account()

    assert discovered == {
        "name": "Parloq Bitly",
        "groupGuid": "group-default",
        "shortDomain": "go.parloq.com",
    }


def test_bitly_rate_limit_is_classified_for_account_failover(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: httpx.Response(
            429,
            headers={"Retry-After": "120"},
            json={"message": "RATE_LIMIT_EXCEEDED"},
        ),
    )

    with pytest.raises(BitlyServiceError) as raised:
        BitlyClient("secret").click_summary("bit.ly/example")

    assert raised.value.category == "rate_limited"
    assert raised.value.retry_after == 120


def test_waba_import_is_encrypted_deduplicated_and_atomic(client, monkeypatch) -> None:
    assert client is not None
    tokens = ("waba-import-token-one", "waba-import-token-two")

    def discover(client: BitlyClient) -> dict[str, str]:
        if client.access_token == tokens[1]:
            raise BitlyServiceError("invalid", category="invalid")
        return {
            "name": "Imported WABA",
            "groupGuid": "group-imported",
            "shortDomain": "bit.ly",
        }

    monkeypatch.setattr(BitlyClient, "discover_account", discover)
    with SessionLocal() as db:
        with pytest.raises(BitlyImportError):
            import_accounts(
                db,
                {"accounts": [{"accessToken": token} for token in tokens]},
            )
        assert db.scalar(
            select(BitlyProviderAccount).where(
                BitlyProviderAccount.token_fingerprint
                == secret_fingerprint(tokens[0])
            )
        ) is None

        result = import_accounts(
            db,
            {
                "accounts": [
                    {"accessToken": tokens[0]},
                    {"accessToken": tokens[0]},
                ]
            },
        )
        assert result == {"source": 2, "imported": 1, "skipped": 1}
        account = db.scalar(
            select(BitlyProviderAccount).where(
                BitlyProviderAccount.token_fingerprint
                == secret_fingerprint(tokens[0])
            )
        )
        assert account is not None
        assert account.group_guid == "group-imported"
        assert account.short_domain == "bit.ly"
        assert tokens[0] not in account.token_ciphertext
        assert decrypt_secret(account.token_ciphertext) == tokens[0]
        db.execute(
            delete(BitlyProviderAccount).where(BitlyProviderAccount.id == account.id)
        )
        db.commit()
