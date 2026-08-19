from __future__ import annotations

from app.services.promotion_event_rate_limits import (
    DEFAULT_PROMOTION_EVENT_RATE_LIMIT_POLICY,
    PromotionEventRateLimitRequest,
    consume_promotion_event_rate_limits,
    normalized_promotion_event_rate_limit_policy,
)


class StubRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def eval(self, _script: str, key_count: int, *values):
        keys = [str(value) for value in values[:key_count]]
        arguments = [int(value) for value in values[key_count:]]
        for index, key in enumerate(keys):
            limit = arguments[index * 2]
            current = self.values.get(key, 0)
            if current >= limit:
                return [0, index + 1, current, self.ttls[key], limit]
        for index, key in enumerate(keys):
            self.values[key] = self.values.get(key, 0) + 1
            self.ttls.setdefault(key, arguments[index * 2 + 1])
        return [1, 0, 0, 0, 0]


def test_event_rate_limit_policy_normalizes_defaults_and_custom_values() -> None:
    policy = normalized_promotion_event_rate_limit_policy(
        {
            "sessionReports": {"maxRequests": 12, "windowSeconds": 30},
            "ip_reports": {"max_requests": 900, "window_seconds": 90},
            "channelReports": {"maxRequests": True, "windowSeconds": -1},
        }
    )

    assert policy["sessionReports"] == {
        "maxRequests": 12,
        "windowSeconds": 30,
    }
    assert policy["ipReports"] == {
        "maxRequests": 900,
        "windowSeconds": 90,
    }
    assert policy["channelReports"] == DEFAULT_PROMOTION_EVENT_RATE_LIMIT_POLICY[
        "channelReports"
    ]
    assert policy["metaDomainReports"] == DEFAULT_PROMOTION_EVENT_RATE_LIMIT_POLICY[
        "metaDomainReports"
    ]


def test_template_and_integration_report_counters_are_partitioned() -> None:
    redis = StubRedis()
    policy = normalized_promotion_event_rate_limit_policy(None)
    policy["sessionReports"] = {"maxRequests": 1, "windowSeconds": 60}
    requests = [PromotionEventRateLimitRequest("sessionReports", "nonce-a")]

    template = consume_promotion_event_rate_limits(
        policy,
        requests,
        partition="template-channel:101",
        client=redis,
    )
    blocked_template = consume_promotion_event_rate_limits(
        policy,
        requests,
        partition="template-channel:101",
        client=redis,
    )
    integration = consume_promotion_event_rate_limits(
        policy,
        requests,
        partition="integration:202:channel:101",
        client=redis,
    )

    assert template.allowed is True
    assert blocked_template.allowed is False
    assert blocked_template.policy_key == "sessionReports"
    assert blocked_template.retry_after_seconds == 60
    assert integration.allowed is True
    assert any("template-channel:101" in key for key in redis.values)
    assert any("integration:202:channel:101" in key for key in redis.values)


def test_multiple_event_report_limits_are_consumed_atomically() -> None:
    redis = StubRedis()
    policy = normalized_promotion_event_rate_limit_policy(None)
    policy["sessionReports"] = {"maxRequests": 2, "windowSeconds": 60}
    policy["ipReports"] = {"maxRequests": 1, "windowSeconds": 600}
    requests = [
        PromotionEventRateLimitRequest("sessionReports", "nonce-a"),
        PromotionEventRateLimitRequest("ipReports", "203.0.113.10"),
        PromotionEventRateLimitRequest("channelReports", "all"),
    ]

    first = consume_promotion_event_rate_limits(
        policy,
        requests,
        partition="template-channel:101",
        client=redis,
    )
    blocked = consume_promotion_event_rate_limits(
        policy,
        requests,
        partition="template-channel:101",
        client=redis,
    )

    assert first.allowed is True
    assert blocked.allowed is False
    assert blocked.policy_key == "ipReports"
    assert blocked.limit == 1
    assert blocked.retry_after_seconds == 600
