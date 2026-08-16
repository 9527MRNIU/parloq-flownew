from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime


SNOWFLAKE_EPOCH = datetime(2026, 8, 1, tzinfo=UTC)
SNOWFLAKE_EPOCH_MS = int(SNOWFLAKE_EPOCH.timestamp() * 1000)
TIMESTAMP_BITS = 41
NODE_BITS = 10
SEQUENCE_BITS = 12
MAX_NODE_ID = (1 << NODE_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
MAX_TIMESTAMP_DELTA = (1 << TIMESTAMP_BITS) - 1
MAX_SNOWFLAKE_ID = (1 << 63) - 1


class SnowflakeError(RuntimeError):
    pass


class SnowflakeGenerator:
    """Thread-safe 64-bit Snowflake generator using the Parloq custom epoch."""

    def __init__(
        self,
        node_id: int,
        *,
        clock_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not 0 <= node_id <= MAX_NODE_ID:
            raise ValueError(f"node_id must be between 0 and {MAX_NODE_ID}")
        self.node_id = node_id
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._last_timestamp = -1
        self._sequence = 0

    def next_id(self) -> int:
        with self._lock:
            now = self._clock_ms()
            if now < SNOWFLAKE_EPOCH_MS:
                raise SnowflakeError("system clock is before the 2026-08-01 Snowflake epoch")

            # A small backwards clock movement must never create a duplicate. Keep
            # issuing from the last observed millisecond until wall time catches up.
            if now < self._last_timestamp:
                now = self._last_timestamp

            if now == self._last_timestamp:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    now = self._wait_next_millisecond(self._last_timestamp)
            else:
                self._sequence = 0

            delta = now - SNOWFLAKE_EPOCH_MS
            if delta > MAX_TIMESTAMP_DELTA:
                raise SnowflakeError("Snowflake timestamp has exhausted its 41-bit range")
            self._last_timestamp = now
            return (
                (delta << (NODE_BITS + SEQUENCE_BITS))
                | (self.node_id << SEQUENCE_BITS)
                | self._sequence
            )

    def _wait_next_millisecond(self, previous: int) -> int:
        while True:
            now = self._clock_ms()
            if now > previous:
                return now
            self._sleep(0.0001)


def _configured_node_id() -> int:
    raw = os.getenv("SNOWFLAKE_NODE_ID", "1").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError("SNOWFLAKE_NODE_ID must be an integer") from exc


_generator = SnowflakeGenerator(_configured_node_id())


def next_snowflake_id() -> int:
    return _generator.next_id()


def new_public_id(prefix: str) -> str:
    normalized = prefix.strip().lower()
    if not normalized or not normalized.replace("-", "").isalnum():
        raise ValueError("public ID prefix must contain only letters, numbers, or hyphens")
    return f"{normalized}_{next_snowflake_id()}"


def parse_snowflake_id(value: str | int) -> int:
    """Parse the canonical decimal representation used by public APIs."""

    raw = str(value).strip()
    if not raw.isascii() or not raw.isdigit() or raw != raw.lstrip("0"):
        raise ValueError("ID must be a canonical decimal Snowflake string")
    parsed = int(raw)
    if parsed <= 0 or parsed > MAX_SNOWFLAKE_ID:
        raise ValueError("ID is outside the signed 64-bit Snowflake range")
    return parsed


def decode_snowflake(value: int) -> dict[str, int | datetime]:
    if value < 0:
        raise ValueError("Snowflake ID must be non-negative")
    delta = value >> (NODE_BITS + SEQUENCE_BITS)
    timestamp_ms = SNOWFLAKE_EPOCH_MS + delta
    return {
        "timestamp": datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
        "nodeId": (value >> SEQUENCE_BITS) & MAX_NODE_ID,
        "sequence": value & MAX_SEQUENCE,
    }
