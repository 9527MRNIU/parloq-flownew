from __future__ import annotations

from fastapi.testclient import TestClient

from app import main


def test_healthz_and_seeded_admin_login(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}

    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["tokenType"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["isAdmin"] is True
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["user"]["isAdmin"] is True

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_security_contract_is_public_and_disabled_in_tests(
    client: TestClient,
) -> None:
    response = client.get("/api/auth/security?username=admin")
    assert response.status_code == 200
    security = response.json()["data"]
    assert security["turnstileEnabled"] is False
    assert security["turnstileRequired"] is False
    assert security["locked"] is False
    assert security["userFailureLimit"] == 5
    assert security["ipFailureLimit"] == 20


def test_readyz_checks_database_redis_and_reports_worker(client, monkeypatch) -> None:
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            return None

    class Engine:
        def connect(self):
            return Connection()

    class Redis:
        def ping(self):
            return True

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())
    monkeypatch.setattr(
        main,
        "worker_status",
        lambda _client: {
            "healthy": True,
            "heartbeatAgeSeconds": 1.0,
            "queueDepth": 0,
            "oldestQueueAgeSeconds": None,
        },
    )
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
    assert response.json()["worker"]["healthy"] is True


def test_readyz_fails_when_a_required_dependency_is_unavailable(
    client, monkeypatch
) -> None:
    class Engine:
        def connect(self):
            raise RuntimeError("database unavailable")

    class Redis:
        def ping(self):
            return True

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())
    monkeypatch.setattr(main, "worker_status", lambda _client: {"healthy": False})
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] == "unavailable"


def test_readyz_fails_when_worker_heartbeat_is_missing(client, monkeypatch) -> None:
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            return None

    class Engine:
        def connect(self):
            return Connection()

    class Redis:
        def ping(self):
            return True

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main, "redis_client", lambda: Redis())
    monkeypatch.setattr(
        main,
        "worker_status",
        lambda _client: {"healthy": False, "heartbeatAgeSeconds": None},
    )
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
    assert response.json()["worker"]["healthy"] is False


def test_bearer_authentication(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["data"]
    client.cookies.clear()
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {login['token']}"}
    )
    assert response.status_code == 200


def test_cookie_authenticated_writes_reject_cross_origin_requests(
    client: TestClient,
) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert login.status_code == 200

    rejected = client.post(
        "/api/auth/logout", headers={"Origin": "https://malicious.example"}
    )
    assert rejected.status_code == 403
    assert client.get("/api/auth/me").status_code == 200

    accepted = client.post(
        "/api/auth/logout", headers={"Origin": "http://localhost:5173"}
    )
    assert accepted.status_code == 200


def test_message_status_has_no_public_mutation_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/personal-accounts/messages/{message_id}/status" not in paths
    assert "/api/internal/wa-gateway/events" in paths
