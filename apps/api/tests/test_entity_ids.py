from __future__ import annotations

from dataclasses import dataclass

from app.entity_ids import entity_id, matches_identifier, parse_entity_id
from app.schemas import AccountProxyBindingCreate, AccountProxyBindingUpdate


@dataclass
class _Row:
    id: int
    public_id: str


def test_entity_ids_are_decimal_strings_above_javascript_safe_integer() -> None:
    row = _Row(id=9_007_199_254_740_993, public_id="legacy_123")

    assert entity_id(row) == "9007199254740993"
    assert parse_entity_id("9007199254740993") == row.id
    assert matches_identifier(row, "9007199254740993") is True
    assert matches_identifier(row, "legacy_123") is True
    assert parse_entity_id("legacy_123") is None


def test_proxy_binding_schema_uses_proxy_id_and_accepts_legacy_alias() -> None:
    canonical = AccountProxyBindingCreate.model_validate(
        {"accountId": "123", "proxyId": "456"}
    )
    legacy = AccountProxyBindingUpdate.model_validate({"proxyPublicId": "ipx_456"})

    assert canonical.model_dump(by_alias=True) == {
        "accountId": "123",
        "proxyId": "456",
    }
    assert legacy.model_dump(by_alias=True) == {"proxyId": "ipx_456"}
