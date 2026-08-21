from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_user_changes_password_and_other_sessions_are_revoked(
    admin_client: TestClient,
) -> None:
    groups = admin_client.get("/api/system/roles").json()["data"]["rows"]
    operator_group = next(row for row in groups if row["systemKey"] == "operator")
    created = admin_client.post(
        "/api/users",
        json={
            "username": "password-change-user",
            "password": "current-password-123",
            "groupId": operator_group["id"],
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["user"]["id"]

    try:
        with TestClient(app) as current_session, TestClient(app) as other_session:
            for client in (current_session, other_session):
                login = client.post(
                    "/api/auth/login",
                    json={
                        "username": "password-change-user",
                        "password": "current-password-123",
                    },
                )
                assert login.status_code == 200, login.text

            wrong_current = current_session.post(
                "/api/auth/password/change",
                json={
                    "currentPassword": "wrong-password",
                    "newPassword": "new-password-456",
                },
            )
            assert wrong_current.status_code == 400
            assert current_session.get("/api/auth/me").status_code == 200

            unchanged = current_session.post(
                "/api/auth/password/change",
                json={
                    "currentPassword": "current-password-123",
                    "newPassword": "current-password-123",
                },
            )
            assert unchanged.status_code == 400

            changed = current_session.post(
                "/api/auth/password/change",
                json={
                    "currentPassword": "current-password-123",
                    "newPassword": "new-password-456",
                },
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["data"]["ok"] is True
            assert current_session.get("/api/auth/me").status_code == 200
            assert other_session.get("/api/auth/me").status_code == 401

            with TestClient(app) as fresh_session:
                old_password = fresh_session.post(
                    "/api/auth/login",
                    json={
                        "username": "password-change-user",
                        "password": "current-password-123",
                    },
                )
                assert old_password.status_code == 401
                new_password = fresh_session.post(
                    "/api/auth/login",
                    json={
                        "username": "password-change-user",
                        "password": "new-password-456",
                    },
                )
                assert new_password.status_code == 200, new_password.text
    finally:
        deleted = admin_client.delete(f"/api/users/{user_id}")
        assert deleted.status_code == 200, deleted.text
