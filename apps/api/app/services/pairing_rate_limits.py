from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import ipaddress

from redis import Redis
from redis.exceptions import RedisError
from starlette.requests import Request

from app.config import get_settings
from app.models import ProtocolNode
from app.services.protocol_nodes import normalized_rate_limit_policy


RATE_LIMIT_KEY_PREFIX = "parloq:public-pairing-rate:v1"

_CONSUME_LIMITS_SCRIPT = """
for index, key in ipairs(KEYS) do
  local offset = (index - 1) * 2
  local limit = tonumber(ARGV[offset + 1])
  local current = tonumber(redis.call('get', key) or '0')
  if current >= limit then
    local ttl = tonumber(redis.call('ttl', key))
    if ttl == nil or ttl < 1 then
      ttl = tonumber(ARGV[offset + 2])
    end
    return {0, index, current, ttl, limit}
  end
end
for index, key in ipairs(KEYS) do
  local offset = (index - 1) * 2
  local count = redis.call('incr', key)
  if count == 1 then
    redis.call('expire', key, tonumber(ARGV[offset + 2]))
  end
end
return {1, 0, 0, 0, 0}
"""


@dataclass(frozen=True, slots=True)
class PairingRateLimitRequest:
    policy_key: str
    subject: str
    partition: str | None = None


@dataclass(frozen=True, slots=True)
class PairingRateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    policy_key: str | None = None
    limit: int | None = None


class PairingRateLimitUnavailable(RuntimeError):
    pass


def redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def public_request_ip(request: Request) -> str:
    candidates = [
        request.headers.get("CF-Connecting-IP", ""),
        request.headers.get("X-Real-IP", ""),
    ]
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        candidates.extend(part.strip() for part in forwarded.split(","))
    for candidate in candidates:
        try:
            return ipaddress.ip_address(candidate.strip()).compressed
        except ValueError:
            continue
    if request.client is not None:
        try:
            peer = ipaddress.ip_address(request.client.host.strip())
            if not (peer.is_private or peer.is_loopback or peer.is_link_local):
                return peer.compressed
        except ValueError:
            pass
    return "unknown"


def _subject_digest(subject: str) -> str:
    return hmac.new(
        get_settings().app_secret_key.encode(),
        subject.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


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
    keys: list[str] = []
    arguments: list[int] = []
    for request in requests:
        rule = policy.get(request.policy_key)
        if rule is None:
            raise ValueError(f"unknown pairing rate-limit policy: {request.policy_key}")
        partition = request.partition or f"protocol:{protocol.id}"
        keys.append(
            f"{RATE_LIMIT_KEY_PREFIX}:{partition}:{request.policy_key}:"
            f"{_subject_digest(request.subject)}"
        )
        arguments.extend((rule["maxRequests"], rule["windowSeconds"]))

    try:
        value = (client or redis_client()).eval(
            _CONSUME_LIMITS_SCRIPT,
            len(keys),
            *keys,
            *arguments,
        )
    except (RedisError, OSError) as exc:
        raise PairingRateLimitUnavailable(
            "public pairing rate-limit store is unavailable"
        ) from exc
    if not isinstance(value, (list, tuple)) or len(value) < 5:
        raise PairingRateLimitUnavailable(
            "public pairing rate-limit store returned an invalid response"
        )
    if int(value[0]) == 1:
        return PairingRateLimitDecision(allowed=True)
    blocked_index = int(value[1]) - 1
    if blocked_index < 0 or blocked_index >= len(requests):
        raise PairingRateLimitUnavailable(
            "public pairing rate-limit store returned an invalid index"
        )
    return PairingRateLimitDecision(
        allowed=False,
        retry_after_seconds=max(int(value[3]), 1),
        policy_key=requests[blocked_index].policy_key,
        limit=int(value[4]),
    )
