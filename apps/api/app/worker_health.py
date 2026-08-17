from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from redis import Redis

from app.task_queue import QUEUE_ENQUEUED_AT_KEY, QUEUE_KEY


logger = logging.getLogger(__name__)
WORKER_HEARTBEAT_KEY = "parloq:hyperlink:worker:heartbeat"
WORKER_HEARTBEAT_INTERVAL_SECONDS = 10
WORKER_HEARTBEAT_TTL_SECONDS = 35


def _snapshot(client: Redis) -> dict[str, Any]:
    now = time.time()
    queue_depth = int(client.llen(QUEUE_KEY))
    if queue_depth == 0:
        client.delete(QUEUE_ENQUEUED_AT_KEY)
        oldest_age: float | None = None
    else:
        oldest = client.zrange(QUEUE_ENQUEUED_AT_KEY, 0, 0, withscores=True)
        oldest_age = max(now - float(oldest[0][1]), 0.0) if oldest else None
    return {
        "timestamp": now,
        "queueDepth": queue_depth,
        "oldestQueueAgeSeconds": round(oldest_age, 3) if oldest_age is not None else None,
    }


def publish_worker_heartbeat(client: Redis) -> None:
    payload = json.dumps(_snapshot(client), separators=(",", ":"))
    client.set(WORKER_HEARTBEAT_KEY, payload, ex=WORKER_HEARTBEAT_TTL_SECONDS)


def _heartbeat_loop(client: Redis) -> None:
    while True:
        try:
            publish_worker_heartbeat(client)
        except Exception:
            logger.exception("task_worker_heartbeat_failed")
        time.sleep(WORKER_HEARTBEAT_INTERVAL_SECONDS)


def start_worker_heartbeat(client: Redis) -> threading.Thread:
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(client,),
        name="task-worker-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def worker_status(client: Redis) -> dict[str, Any]:
    raw = client.get(WORKER_HEARTBEAT_KEY)
    if not raw:
        return {"healthy": False, "heartbeatAgeSeconds": None}
    try:
        payload = json.loads(str(raw))
        age = max(time.time() - float(payload["timestamp"]), 0.0)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"healthy": False, "heartbeatAgeSeconds": None}
    return {
        "healthy": age <= WORKER_HEARTBEAT_TTL_SECONDS,
        "heartbeatAgeSeconds": round(age, 3),
        "queueDepth": int(payload.get("queueDepth", 0)),
        "oldestQueueAgeSeconds": payload.get("oldestQueueAgeSeconds"),
    }


def healthcheck() -> int:
    from app.task_queue import redis_client

    try:
        client = redis_client()
        client.ping()
        return 0 if worker_status(client)["healthy"] else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(healthcheck())
