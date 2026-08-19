from __future__ import annotations

from redis import Redis

from app.config import get_settings
from app.services.public_rate_limits import (
    RateLimitDecision,
    RateLimitRequest,
    RateLimitUnavailable,
    consume_rate_limits,
)


RATE_LIMIT_KEY_PREFIX = "parloq:public-promotion-report-rate:v1"

DEFAULT_PROMOTION_EVENT_RATE_LIMIT_POLICY: dict[str, dict[str, int]] = {
    "sessionReports": {"maxRequests": 60, "windowSeconds": 60},
    "ipReports": {"maxRequests": 600, "windowSeconds": 60},
    "channelReports": {"maxRequests": 10_000, "windowSeconds": 60},
    "metaDomainReports": {"maxRequests": 5, "windowSeconds": 600},
}

PromotionEventRateLimitRequest = RateLimitRequest
PromotionEventRateLimitDecision = RateLimitDecision
PromotionEventRateLimitUnavailable = RateLimitUnavailable


def normalized_promotion_event_rate_limit_policy(
    value: dict | None,
) -> dict[str, dict[str, int]]:
    source = value if isinstance(value, dict) else {}
    snake_aliases = {
        "sessionReports": "session_reports",
        "ipReports": "ip_reports",
        "channelReports": "channel_reports",
        "metaDomainReports": "meta_domain_reports",
    }
    result: dict[str, dict[str, int]] = {}
    for key, defaults in DEFAULT_PROMOTION_EVENT_RATE_LIMIT_POLICY.items():
        raw = source.get(key, source.get(snake_aliases[key], {}))
        rule = raw if isinstance(raw, dict) else {}
        max_requests = rule.get("maxRequests", rule.get("max_requests"))
        window_seconds = rule.get("windowSeconds", rule.get("window_seconds"))
        result[key] = {
            "maxRequests": (
                max_requests
                if isinstance(max_requests, int)
                and not isinstance(max_requests, bool)
                and 1 <= max_requests <= 1_000_000
                else defaults["maxRequests"]
            ),
            "windowSeconds": (
                window_seconds
                if isinstance(window_seconds, int)
                and not isinstance(window_seconds, bool)
                and 1 <= window_seconds <= 86_400
                else defaults["windowSeconds"]
            ),
        }
    return result


def consume_promotion_event_rate_limits(
    policy: dict[str, dict[str, int]],
    requests: list[PromotionEventRateLimitRequest],
    *,
    partition: str,
    client: Redis | None = None,
) -> PromotionEventRateLimitDecision:
    if not requests or (
        get_settings().promotion_event_rate_limit_mock and client is None
    ):
        return PromotionEventRateLimitDecision(allowed=True)
    return consume_rate_limits(
        normalized_promotion_event_rate_limit_policy(policy),
        requests,
        key_prefix=RATE_LIMIT_KEY_PREFIX,
        default_partition=partition,
        client=client,
    )
