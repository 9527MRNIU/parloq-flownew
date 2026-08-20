from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import DomainRecord, UserAccount


def test_builtin_operator_group_is_seeded(admin_client: TestClient) -> None:
    rows = admin_client.get("/api/user-groups").json()["data"]["rows"]
    assert any(row["systemKey"] == "operator" for row in rows)


def test_user_and_group_crud(admin_client: TestClient) -> None:
    group_response = admin_client.post(
        "/api/user-groups", json={"name": "运营组", "description": "第一版运营账号"}
    )
    assert group_response.status_code == 201
    group_id = group_response.json()["data"]["group"]["id"]

    user_response = admin_client.post(
        "/api/users",
        json={
            "username": "operator-one",
            "password": "secure-pass-123",
            "displayName": "Operator One",
            "groupId": group_id,
        },
    )
    assert user_response.status_code == 201
    assert user_response.json()["data"]["user"]["isAdmin"] is False
    user_id = user_response.json()["data"]["user"]["id"]

    update = admin_client.patch(
        f"/api/users/{user_id}", json={"displayName": "Updated Operator"}
    )
    assert update.status_code == 200
    assert update.json()["data"]["user"]["displayName"] == "Updated Operator"

    assert admin_client.delete(f"/api/user-groups/{group_id}").status_code == 409
    assert admin_client.delete(f"/api/users/{user_id}").status_code == 200
    users = admin_client.get("/api/users").json()["data"]["rows"]
    assert all(user["id"] != user_id for user in users)
    assert admin_client.delete(f"/api/user-groups/{group_id}").status_code == 200


def test_current_admin_cannot_delete_itself(admin_client: TestClient) -> None:
    me = admin_client.get("/api/auth/me").json()["data"]["user"]
    response = admin_client.delete(f"/api/users/{me['id']}")
    assert response.status_code == 400


def test_user_list_is_server_paginated_and_searchable(admin_client: TestClient) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    for index in range(3):
        response = admin_client.post(
            "/api/users",
            json={
                "username": f"paging-user-{index}",
                "password": "secure-pass-123",
                "displayName": f"Paging Person {index}",
                "groupId": operator["id"],
            },
        )
        assert response.status_code == 201
    first = admin_client.get("/api/users?keyword=paging-user-&page=1&pageSize=2")
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["pageSize"] == 2
    assert len(data["rows"]) == 2
    second = admin_client.get("/api/users?keyword=Paging%20Person&page=2&pageSize=2")
    assert second.json()["data"]["total"] == 3
    assert len(second.json()["data"]["rows"]) == 1


def test_user_delete_requires_owned_resources_to_be_removed_then_hard_deletes(
    admin_client: TestClient,
) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    created = admin_client.post(
        "/api/users",
        json={
            "username": "lifecycle-owner",
            "password": "secure-pass-123",
            "groupId": operator["id"],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["user"]["id"]
    owner = TestClient(app)
    try:
        assert owner.post(
            "/api/auth/login",
            json={"username": "lifecycle-owner", "password": "secure-pass-123"},
        ).status_code == 200
        domain = owner.post(
            "/api/domains", json={"hostname": "lifecycle-owned.example"}
        )
        assert domain.status_code == 201
        domain_id = domain.json()["data"]["domain"]["id"]
        blocked = admin_client.delete(f"/api/users/{user_id}")
        assert blocked.status_code == 409, blocked.text
        assert owner.delete(f"/api/domains/{domain_id}").status_code == 200
        assert admin_client.delete(f"/api/users/{user_id}").status_code == 200
        assert owner.get("/api/auth/me").status_code == 401
        assert owner.post(
            "/api/auth/login",
            json={"username": "lifecycle-owner", "password": "secure-pass-123"},
        ).status_code == 401
        with SessionLocal() as db:
            user = db.scalar(
                select(UserAccount).where(UserAccount.username == "lifecycle-owner")
            )
            resource = db.scalar(
                select(DomainRecord).where(DomainRecord.id == int(domain_id))
            )
            assert user is None
            assert resource is None
    finally:
        owner.close()


def test_password_change_revokes_existing_sessions(admin_client: TestClient) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    created = admin_client.post(
        "/api/users",
        json={
            "username": "password-rotation-user",
            "password": "secure-pass-123",
            "groupId": operator["id"],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["user"]["id"]
    owner = TestClient(app)
    try:
        assert owner.post(
            "/api/auth/login",
            json={"username": "password-rotation-user", "password": "secure-pass-123"},
        ).status_code == 200
        assert owner.get("/api/auth/me").status_code == 200

        changed = admin_client.patch(
            f"/api/users/{user_id}", json={"password": "new-secure-pass-456"}
        )
        assert changed.status_code == 200
        assert owner.get("/api/auth/me").status_code == 401
        assert owner.post(
            "/api/auth/login",
            json={"username": "password-rotation-user", "password": "secure-pass-123"},
        ).status_code == 401
        assert owner.post(
            "/api/auth/login",
            json={"username": "password-rotation-user", "password": "new-secure-pass-456"},
        ).status_code == 200
    finally:
        owner.close()
