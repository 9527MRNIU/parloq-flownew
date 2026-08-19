from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import ipaddress

from redis import Redis
from redis.exceptions import RedisError
from starlette.requests import Request

from app.config import get_settings


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
class RateLimitRequest:
    policy_key: str
    subject: str
    partition: str | None = None


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    policy_key: str | None = None
    limit: int | None = None


class RateLimitUnavailable(RuntimeError):
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


def consume_rate_limits(
    policy: dict[str, dict[str, int | None]],
    requests: list[RateLimitRequest],
    *,
    key_prefix: str,
    default_partition: str,
    client: Redis | None = None,
) -> RateLimitDecision:
    if not requests:
        return RateLimitDecision(allowed=True)

    keys: list[str] = []
    arguments: list[int] = []
    active_requests: list[RateLimitRequest] = []
    for request in requests:
        rule = policy.get(request.policy_key)
        if rule is None:
            raise ValueError(f"unknown rate-limit policy: {request.policy_key}")
        max_requests = rule["maxRequests"]
        if max_requests is None:
            continue
        partition = request.partition or default_partition
        active_requests.append(request)
        keys.append(
            f"{key_prefix}:{partition}:{request.policy_key}:"
            f"{_subject_digest(request.subject)}"
        )
        arguments.extend((max_requests, int(rule["windowSeconds"] or 1)))

    if not active_requests:
        return RateLimitDecision(allowed=True)

    try:
        value = (client or redis_client()).eval(
            _CONSUME_LIMITS_SCRIPT,
            len(keys),
            *keys,
            *arguments,
        )
    except (RedisError, OSError) as exc:
        raise RateLimitUnavailable("public rate-limit store is unavailable") from exc
    if not isinstance(value, (list, tuple)) or len(value) < 5:
        raise RateLimitUnavailable(
            "public rate-limit store returned an invalid response"
        )
    if int(value[0]) == 1:
        return RateLimitDecision(allowed=True)
    blocked_index = int(value[1]) - 1
    if blocked_index < 0 or blocked_index >= len(active_requests):
        raise RateLimitUnavailable(
            "public rate-limit store returned an invalid index"
        )
    return RateLimitDecision(
        allowed=False,
        retry_after_seconds=max(int(value[3]), 1),
        policy_key=active_requests[blocked_index].policy_key,
        limit=int(value[4]),
    )
