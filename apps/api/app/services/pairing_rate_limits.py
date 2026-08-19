from __future__ import annotations

from redis import Redis

from app.config import get_settings
from app.models import ProtocolNode
from app.services.protocol_nodes import normalized_rate_limit_policy
from app.services.public_rate_limits import (
    RateLimitDecision,
    RateLimitRequest,
    RateLimitUnavailable,
    consume_rate_limits,
    public_request_ip,
)


RATE_LIMIT_KEY_PREFIX = "parloq:public-pairing-rate:v1"

PairingRateLimitRequest = RateLimitRequest
PairingRateLimitDecision = RateLimitDecision
PairingRateLimitUnavailable = RateLimitUnavailable


def consume_pairing_rate_limits(
    protocol: ProtocolNode,
    requests: list[PairingRateLimitRequest],
    *,
    client: Redis | None = None,
) -> PairingRateLimitDecision:
    if not requests or (
        get_settings().pairing_rate_limit_mock and client is None
    ):
        return PairingRateLimitDecision(allowed=True)

    policy = normalized_rate_limit_policy(protocol.rate_limit_policy_json)
    return consume_rate_limits(
        policy,
        requests,
        key_prefix=RATE_LIMIT_KEY_PREFIX,
        default_partition=f"protocol:{protocol.id}",
        client=client,
    )
