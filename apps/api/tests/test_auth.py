from __future__ import annotations

from fastapi.testclient import TestClient


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


def test_bearer_authentication(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["data"]
    client.cookies.clear()
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {login['token']}"}
    )
    assert response.status_code == 200


def test_message_status_has_no_public_mutation_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/personal-accounts/messages/{message_id}/status" not in paths
    assert "/api/internal/wa-gateway/events" in paths
