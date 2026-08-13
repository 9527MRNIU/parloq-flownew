from __future__ import annotations

from redis import Redis

from app.config import get_settings


QUEUE_KEY = "parloq:hyperlink:task-queue"


def redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def enqueue_hyperlink_task(task_public_id: str) -> None:
    if get_settings().task_queue_mock:
        return
    redis_client().rpush(QUEUE_KEY, task_public_id)
