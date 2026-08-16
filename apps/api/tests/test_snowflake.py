from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger

from app.database import Base
from app import models as _models  # noqa: F401 - registers every table
from app.snowflake import (
    SNOWFLAKE_EPOCH_MS,
    SnowflakeGenerator,
    decode_snowflake,
    new_public_id,
    next_snowflake_id,
    parse_snowflake_id,
)


def test_snowflake_uses_custom_epoch_and_layout() -> None:
    timestamp = SNOWFLAKE_EPOCH_MS + 12_345
    generator = SnowflakeGenerator(37, clock_ms=lambda: timestamp)

    first = generator.next_id()
    second = generator.next_id()

    assert first < second
    assert decode_snowflake(first) == {
        "timestamp": datetime.fromtimestamp(timestamp / 1000, tz=UTC),
        "nodeId": 37,
        "sequence": 0,
    }
    assert decode_snowflake(second)["sequence"] == 1


def test_snowflake_survives_small_clock_rollback() -> None:
    values = iter(
        [
            SNOWFLAKE_EPOCH_MS + 100,
            SNOWFLAKE_EPOCH_MS + 99,
            SNOWFLAKE_EPOCH_MS + 101,
        ]
    )
    generator = SnowflakeGenerator(2, clock_ms=lambda: next(values))

    ids = [generator.next_id(), generator.next_id(), generator.next_id()]

    assert ids == sorted(set(ids))
    assert decode_snowflake(ids[1])["timestamp"] == decode_snowflake(ids[0])["timestamp"]


def test_all_internal_primary_and_foreign_ids_are_bigint() -> None:
    violations = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if (column.primary_key or column.foreign_keys)
        and not isinstance(column.type, BigInteger)
    ]

    assert violations == []


def test_all_internal_primary_ids_use_snowflake_generator() -> None:
    violations = []
    for table in Base.metadata.sorted_tables:
        for column in table.primary_key.columns:
            default = column.default
            default_callable = (
                getattr(default.arg, "__wrapped__", default.arg) if default else None
            )
            if default_callable is not next_snowflake_id:
                violations.append(f"{table.name}.{column.name}")

    assert violations == []


def test_public_business_id_wraps_a_snowflake() -> None:
    public_id = new_public_id("ptpl")
    prefix, raw = public_id.split("_", 1)

    assert prefix == "ptpl"
    assert decode_snowflake(int(raw))["timestamp"] >= datetime(2026, 8, 1, tzinfo=UTC)


def test_api_snowflake_parser_requires_canonical_signed_decimal() -> None:
    value = 9_007_199_254_740_993
    assert parse_snowflake_id(str(value)) == value
    for invalid in ("0", "01", "-1", "+1", "1.0", "wa_1", str(1 << 63)):
        try:
            parse_snowflake_id(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"non-canonical ID was accepted: {invalid}")
