from __future__ import annotations

import json
from dataclasses import replace

from cryptography.fernet import Fernet

from app.config import get_settings
from app.security import decrypt_secret, encrypt_secret
from app.services import login_security
from app.task_queue import QUEUE_ENQUEUED_AT_KEY, QUEUE_KEY
from app.worker_health import (
    WORKER_HEARTBEAT_KEY,
    publish_worker_heartbeat,
    worker_status,
)


class _Pipeline:
    def __init__(self, client: "_FakeRedis") -> None:
        self.client = client
        self.operations: list[tuple[str, tuple, dict]] = []

    def incr(self, *args, **kwargs):
        self.operations.append(("incr", args, kwargs))
        return self

    def expire(self, *args, **kwargs):
        self.operations.append(("expire", args, kwargs))
        return self

    def set(self, *args, **kwargs):
        self.operations.append(("set", args, kwargs))
        return self

    def execute(self) -> list:
        return [getattr(self.client, name)(*args, **kwargs) for name, args, kwargs in self.operations]


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.sorted_sets: dict[str, list[tuple[str, float]]] = {}

    def pipeline(self, **_kwargs) -> _Pipeline:
        return _Pipeline(self)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def mget(self, *keys: str) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.values.pop(key, None) is not None)
            self.ttls.pop(key, None)
            self.sorted_sets.pop(key, None)
        return removed

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def zrange(self, key: str, _start: int, _end: int, *, withscores: bool = False):
        rows = sorted(self.sorted_sets.get(key, []), key=lambda item: item[1])[:1]
        return rows if withscores else [item[0] for item in rows]


def test_login_failures_trigger_turnstile_and_short_lock(monkeypatch) -> None:
    fake = _FakeRedis()
    settings = replace(
        get_settings(),
        login_security_enabled=True,
        turnstile_enabled=True,
        login_user_failure_limit=2,
        login_ip_failure_limit=20,
        login_lock_seconds=600,
    )
    monkeypatch.setattr(login_security, "get_settings", lambda: settings)
    monkeypatch.setattr(login_security, "_redis", lambda _settings: fake)

    initial = login_security.state("operator", "203.0.113.10")
    assert initial.turnstile_required is False
    assert initial.locked is False

    first = login_security.record_failure("operator", "203.0.113.10")
    assert first.turnstile_required is True
    assert first.locked is False
    assert login_security.state("operator", "203.0.113.10").turnstile_required is True

    second = login_security.record_failure("operator", "203.0.113.10")
    assert second.locked is True
    locked = login_security.state("operator", "203.0.113.10")
    assert locked.locked is True
    assert locked.retry_after_seconds == 600
    assert all("operator" not in key for key in fake.values)
    assert all("203.0.113.10" not in key for key in fake.values)


def test_encryption_keyring_supports_rotation_and_legacy_values(monkeypatch) -> None:
    original = get_settings()
    monkeypatch.setattr("app.security.get_settings", lambda: original)
    legacy = encrypt_secret("legacy-secret")
    assert legacy.startswith("v1:")

    first_key = Fernet.generate_key().decode("ascii")
    second_key = Fernet.generate_key().decode("ascii")
    first = replace(
        original,
        data_encryption_active_key_id="2026-08-a",
        data_encryption_keys=(("2026-08-a", first_key),),
    )
    monkeypatch.setattr("app.security.get_settings", lambda: first)
    encrypted = encrypt_secret("rotating-secret")
    assert encrypted.startswith("v2:2026-08-a:")
    assert decrypt_secret(encrypted) == "rotating-secret"
    assert decrypt_secret(legacy) == "legacy-secret"

    rotated = replace(
        first,
        data_encryption_active_key_id="2026-08-b",
        data_encryption_keys=(
            ("2026-08-a", first_key),
            ("2026-08-b", second_key),
        ),
    )
    monkeypatch.setattr("app.security.get_settings", lambda: rotated)
    assert decrypt_secret(encrypted) == "rotating-secret"
    assert encrypt_secret("new-secret").startswith("v2:2026-08-b:")


def test_worker_heartbeat_reports_queue_depth_and_age(monkeypatch) -> None:
    fake = _FakeRedis()
    fake.lists[QUEUE_KEY] = ["task-1"]
    fake.sorted_sets[QUEUE_ENQUEUED_AT_KEY] = [("task-1", 90.0)]
    monkeypatch.setattr("app.worker_health.time.time", lambda: 100.0)

    publish_worker_heartbeat(fake)  # type: ignore[arg-type]
    payload = json.loads(fake.values[WORKER_HEARTBEAT_KEY])
    assert payload["queueDepth"] == 1
    assert payload["oldestQueueAgeSeconds"] == 10.0
    assert worker_status(fake)["healthy"] is True  # type: ignore[arg-type]
