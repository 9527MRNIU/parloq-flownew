from __future__ import annotations

import time

from redis import Redis

from app.config import get_settings


QUEUE_KEY = "parloq:hyperlink:task-queue"
QUEUE_ENQUEUED_AT_KEY = "parloq:hyperlink:task-queue:enqueued-at"
QUEUE_MARKER_PREFIX = "parloq:hyperlink:task-queued:"
QUEUE_MARKER_TTL_SECONDS = 15 * 60
DELAYED_QUEUE_KEY = "parloq:hyperlink:task-delayed"


def redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def task_queue_marker(task_id: str) -> str:
    return f"{QUEUE_MARKER_PREFIX}{task_id}"


def enqueue_hyperlink_task(task_id: str) -> bool:
    """Queue a task once until a worker consumes its marker.

    The database remains the source of truth.  This marker only prevents a
    recovery scan and an HTTP start request from flooding Redis with duplicate
    task IDs.
    """

    if get_settings().task_queue_mock:
        return False
    client = redis_client()
    marker = task_queue_marker(task_id)
    # Keep the de-duplication marker and queue insertion atomic. Otherwise a
    # worker process dying between SET and RPUSH can suppress recovery until
    # the marker expires even though no queue item exists.
    queued = client.eval(
        """
        if redis.call('exists', KEYS[1]) == 1 then
          return 0
        end
        redis.call('set', KEYS[1], '1', 'EX', ARGV[2])
        redis.call('rpush', KEYS[2], ARGV[1])
        redis.call('zadd', KEYS[3], ARGV[3], ARGV[1])
        return 1
        """,
        3,
        marker,
        QUEUE_KEY,
        QUEUE_ENQUEUED_AT_KEY,
        task_id,
        QUEUE_MARKER_TTL_SECONDS,
        time.time(),
    )
    return bool(queued)


def schedule_hyperlink_task(task_id: str, delay_seconds: int) -> bool:
    """Schedule the earliest durable Redis wakeup for a retrying task."""

    if get_settings().task_queue_mock:
        return False
    if delay_seconds <= 0:
        return enqueue_hyperlink_task(task_id)
    client = redis_client()
    due_at = time.time() + delay_seconds
    changed = client.eval(
        """
        local current = redis.call('zscore', KEYS[1], ARGV[1])
        if current and tonumber(current) <= tonumber(ARGV[2]) then
          return 0
        end
        redis.call('zadd', KEYS[1], ARGV[2], ARGV[1])
        return 1
        """,
        1,
        DELAYED_QUEUE_KEY,
        task_id,
        due_at,
    )
    return bool(changed)


def dispatch_due_hyperlink_tasks(limit: int = 100) -> int:
    """Move due retry wakeups into the ordinary de-duplicated work queue."""

    if get_settings().task_queue_mock:
        return 0
    client = redis_client()
    task_ids = client.eval(
        """
        local values = redis.call(
          'zrangebyscore', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2]
        )
        if #values > 0 then
          redis.call('zrem', KEYS[1], unpack(values))
        end
        return values
        """,
        1,
        DELAYED_QUEUE_KEY,
        time.time(),
        limit,
    )
    queued = 0
    for task_id in task_ids or []:
        queued += int(enqueue_hyperlink_task(str(task_id)))
    return queued
