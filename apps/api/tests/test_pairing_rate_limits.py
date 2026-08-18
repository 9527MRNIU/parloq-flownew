from __future__ import annotations

import json

from starlette.requests import Request

from app.models import ProtocolNode
from app.routers.promotion import _pairing_rate_limit_response
from app.services.pairing_rate_limits import (
    PairingRateLimitDecision,
    PairingRateLimitRequest,
    consume_pairing_rate_limits,
    public_request_ip,
)
from app.services.protocol_nodes import (
    DEFAULT_RATE_LIMIT_POLICY,
    normalized_rate_limit_policy,
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


def _protocol() -> ProtocolNode:
    policy = normalized_rate_limit_policy(DEFAULT_RATE_LIMIT_POLICY)
    policy["visitorCheck"] = {"maxRequests": 2, "windowSeconds": 600}
    policy["ipStart"] = {"maxRequests": 1, "windowSeconds": 60}
    return ProtocolNode(id=123, rate_limit_policy_json=policy)


def test_multiple_pairing_limits_are_consumed_atomically() -> None:
    redis = StubRedis()
    protocol = _protocol()
    visitor = PairingRateLimitRequest("visitorCheck", "channel:1:visitor:abc")
    first_ip = PairingRateLimitRequest("ipStart", "channel:1:ip:203.0.113.1")

    first = consume_pairing_rate_limits(
        protocol, [visitor, first_ip], client=redis
    )
    assert first.allowed is True

    blocked_ip = consume_pairing_rate_limits(
        protocol, [visitor, first_ip], client=redis
    )
    assert blocked_ip.allowed is False
    assert blocked_ip.policy_key == "ipStart"
    assert blocked_ip.limit == 1
    assert blocked_ip.retry_after_seconds == 60

    second_ip = PairingRateLimitRequest(
        "ipStart", "channel:1:ip:203.0.113.2"
    )
    second = consume_pairing_rate_limits(
        protocol, [visitor, second_ip], client=redis
    )
    assert second.allowed is True
    blocked_visitor = consume_pairing_rate_limits(
        protocol,
        [
            visitor,
            PairingRateLimitRequest(
                "ipStart", "channel:1:ip:203.0.113.3"
            ),
        ],
        client=redis,
    )
    assert blocked_visitor.allowed is False
    assert blocked_visitor.policy_key == "visitorCheck"
    assert all("203.0.113" not in key and "visitor:abc" not in key for key in redis.values)


def test_unlimited_channel_attempt_does_not_consume_a_counter() -> None:
    redis = StubRedis()
    protocol = _protocol()
    decision = consume_pairing_rate_limits(
        protocol,
        [PairingRateLimitRequest("channelAttempt", "channel:1")],
        client=redis,
    )

    assert decision.allowed is True
    assert redis.values == {}


def test_fingerprint_backed_visitor_and_ip_limits_remain_independent() -> None:
    redis = StubRedis()
    protocol = _protocol()
    protocol.rate_limit_policy_json["visitorCheck"] = {
        "maxRequests": 1,
        "windowSeconds": 600,
    }
    first = consume_pairing_rate_limits(
        protocol,
        [
            PairingRateLimitRequest(
                "visitorCheck", "channel:1:fingerprint:device-a"
            ),
            PairingRateLimitRequest("ipStart", "channel:1:ip:203.0.113.10"),
        ],
        client=redis,
    )
    assert first.allowed is True

    blocked_device = consume_pairing_rate_limits(
        protocol,
        [
            PairingRateLimitRequest(
                "visitorCheck", "channel:1:fingerprint:device-a"
            ),
            PairingRateLimitRequest("ipStart", "channel:1:ip:203.0.113.11"),
        ],
        client=redis,
    )
    assert blocked_device.allowed is False
    assert blocked_device.policy_key == "visitorCheck"

    # A different device still reaches the independent IP counter.
    blocked_ip = consume_pairing_rate_limits(
        protocol,
        [
            PairingRateLimitRequest(
                "visitorCheck", "channel:1:fingerprint:device-b"
            ),
            PairingRateLimitRequest("ipStart", "channel:1:ip:203.0.113.10"),
        ],
        client=redis,
    )
    assert blocked_ip.allowed is False
    assert blocked_ip.policy_key == "ipStart"


def test_public_request_ip_prefers_valid_forwarded_ingress_address() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"cf-connecting-ip", b"2001:db8::1"),
                (b"x-real-ip", b"198.51.100.2"),
            ],
            "client": ("10.0.0.3", 1234),
        }
    )
    assert public_request_ip(request) == "2001:db8::1"


def test_public_rate_limit_response_has_stable_retry_contract() -> None:
    response = _pairing_rate_limit_response(
        PairingRateLimitDecision(
            allowed=False,
            retry_after_seconds=17,
            policy_key="status",
            limit=60,
        )
    )
    assert response is not None
    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.headers["access-control-expose-headers"] == "Retry-After"
    assert json.loads(response.body) == {
        "error": {
            "code": "rate_limited",
            "message": "绑定请求过于频繁，请稍后再试",
            "retryable": True,
            "retryAfterSeconds": 17,
        }
    }
