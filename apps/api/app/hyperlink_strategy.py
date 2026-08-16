from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


NoAccountAction = Literal["wait", "pause"]


DEFAULT_STRATEGY_RULES: dict[str, Any] = {
    "retryBackoffSeconds": 5,
    "noAccountAction": "wait",
    "sendJitterMs": 0,
    "accountFailureThreshold": 3,
    "accountCooldownSeconds": 300,
    "deliveryLeaseSeconds": 120,
}


@dataclass(frozen=True, slots=True)
class HyperlinkStrategyPolicy:
    # concurrency means concurrently-held account slots, not message threads.
    max_qps: int
    concurrency: int
    buffer_size: int
    retry_limit: int
    retry_backoff_seconds: int
    no_account_action: NoAccountAction
    send_jitter_ms: int
    account_failure_threshold: int
    account_cooldown_seconds: int
    delivery_lease_seconds: int


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def normalize_strategy_rules(value: object) -> dict[str, Any]:
    """Return the sticky-slot rule set, including safe legacy defaults."""

    source = value if isinstance(value, dict) else {}
    no_account_action = str(source.get("noAccountAction") or "wait")
    if no_account_action not in {"wait", "pause"}:
        no_account_action = "wait"
    return {
        "retryBackoffSeconds": _bounded_int(
            source.get("retryBackoffSeconds"), 5, 0, 3600
        ),
        "noAccountAction": no_account_action,
        "sendJitterMs": _bounded_int(source.get("sendJitterMs"), 0, 0, 60_000),
        "accountFailureThreshold": _bounded_int(
            source.get("accountFailureThreshold"), 3, 1, 100
        ),
        "accountCooldownSeconds": _bounded_int(
            source.get("accountCooldownSeconds"), 300, 0, 86_400
        ),
        "deliveryLeaseSeconds": _bounded_int(
            source.get("deliveryLeaseSeconds"), 120, 30, 900
        ),
    }


def merge_strategy_rules(
    current: object,
    *,
    retry_backoff_seconds: int | None = None,
    no_account_action: str | None = None,
    send_jitter_ms: int | None = None,
    account_failure_threshold: int | None = None,
    account_cooldown_seconds: int | None = None,
) -> dict[str, Any]:
    merged = normalize_strategy_rules(current)
    updates = {
        "retryBackoffSeconds": retry_backoff_seconds,
        "noAccountAction": no_account_action,
        "sendJitterMs": send_jitter_ms,
        "accountFailureThreshold": account_failure_threshold,
        "accountCooldownSeconds": account_cooldown_seconds,
    }
    merged.update({key: value for key, value in updates.items() if value is not None})
    return normalize_strategy_rules(merged)


def strategy_policy(strategy) -> HyperlinkStrategyPolicy:
    rules = normalize_strategy_rules(strategy.rules_json)
    max_qps = _bounded_int(strategy.max_qps, 10, 1, 100)
    concurrency = _bounded_int(strategy.concurrency, 1, 1, 1000)
    # The database batch is an internal short lease window. It intentionally
    # remains hidden from users and is derived from account slots and QPS.
    adaptive_buffer = max(concurrency * max_qps * 2, concurrency, 32)
    configured_cap = _bounded_int(strategy.batch_size, 1000, 32, 10_000)
    return HyperlinkStrategyPolicy(
        max_qps=max_qps,
        concurrency=concurrency,
        buffer_size=min(adaptive_buffer, configured_cap, 2000),
        retry_limit=_bounded_int(strategy.retry_limit, 1, 0, 10),
        retry_backoff_seconds=rules["retryBackoffSeconds"],
        no_account_action=rules["noAccountAction"],
        send_jitter_ms=rules["sendJitterMs"],
        account_failure_threshold=rules["accountFailureThreshold"],
        account_cooldown_seconds=rules["accountCooldownSeconds"],
        delivery_lease_seconds=rules["deliveryLeaseSeconds"],
    )
