from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import false, or_
from sqlalchemy.sql.elements import ColumnElement

from app.snowflake import parse_snowflake_id


def entity_id(value: Any) -> str:
    """Serialize a Parloq entity primary key without losing 64-bit precision."""
    raw = value.id if hasattr(value, "id") else value
    if isinstance(raw, bool):
        raise ValueError("entity ID cannot be boolean")
    return str(parse_snowflake_id(raw))


def parse_entity_id(value: str | int) -> int | None:
    """Return a canonical decimal BIGINT, or None for a legacy public ID."""
    text = str(value).strip()
    try:
        return parse_snowflake_id(text)
    except ValueError:
        return None


def identifier_filter(model: type, value: str | int) -> ColumnElement[bool]:
    """Match the Snowflake PK, with a hidden public_id fallback for old clients."""
    parsed = parse_entity_id(value)
    if parsed is not None:
        return model.id == parsed
    public_id = getattr(model, "public_id", None)
    if public_id is None:
        return false()
    return public_id == str(value)


def identifiers_filter(
    model: type, values: Iterable[str | int]
) -> ColumnElement[bool]:
    identifiers = list(dict.fromkeys(str(value).strip() for value in values))
    if not identifiers:
        return false()
    snowflakes = [
        parsed
        for identifier in identifiers
        if (parsed := parse_entity_id(identifier)) is not None
    ]
    legacy = [
        identifier
        for identifier in identifiers
        if parse_entity_id(identifier) is None
    ]
    clauses: list[ColumnElement[bool]] = []
    if snowflakes:
        clauses.append(model.id.in_(snowflakes))
    public_id = getattr(model, "public_id", None)
    if legacy and public_id is not None:
        clauses.append(public_id.in_(legacy))
    return or_(*clauses) if clauses else false()


def matches_identifier(item: Any, value: str | int) -> bool:
    parsed = parse_entity_id(value)
    if parsed is not None:
        return int(item.id) == parsed
    return getattr(item, "public_id", None) == str(value)
