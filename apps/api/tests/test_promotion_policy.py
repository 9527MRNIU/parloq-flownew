from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import PromotionTemplatePolicy, UserAccount


def _create_operator(admin: TestClient, username: str) -> None:
    groups = admin.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    response = admin.post(
        "/api/users",
        json={
            "username": username,
            "password": "policy-password-123",
            "groupId": operator["id"],
        },
    )
    assert response.status_code == 201, response.text


def test_template_policy_defaults_update_validation_and_tenant_isolation(
    admin_client: TestClient,
) -> None:
    _create_operator(admin_client, "template-policy-tenant")
    admin_before = admin_client.get("/api/promotion/template-policy").json()["data"][
        "policy"
    ]
    operator = TestClient(app)
    try:
        login = operator.post(
            "/api/auth/login",
            json={
                "username": "template-policy-tenant",
                "password": "policy-password-123",
            },
        )
        assert login.status_code == 200
        operator_default = operator.get("/api/promotion/template-policy")
        assert operator_default.status_code == 200, operator_default.text
        operator_policy = operator_default.json()["data"]["policy"]
        assert operator_policy["id"].isdigit()
        assert {key: value for key, value in operator_policy.items() if key != "id"} == {
            "protectionMode": "strict",
            "devtoolsAction": "blank",
            "lockViewportZoom": True,
            "deviceSignals": "fingerprint",
            "updatedAt": operator_default.json()["data"]["policy"]["updatedAt"],
        }

        updated = operator.patch(
            "/api/promotion/template-policy",
            json={
                "protectionMode": "basic",
                "devtoolsAction": "log",
                "lockViewportZoom": False,
                "deviceSignals": "standard",
            },
        )
        assert updated.status_code == 200, updated.text
        updated_policy = updated.json()["data"]["policy"]
        assert updated_policy["id"] == operator_policy["id"]
        assert {
            key: value
            for key, value in updated_policy.items()
            if key not in {"id", "updatedAt"}
        } == {
            "protectionMode": "basic",
            "devtoolsAction": "log",
            "lockViewportZoom": False,
            "deviceSignals": "standard",
        }
        assert operator.get("/api/promotion/template-policy").json()["data"][
            "policy"
        ]["protectionMode"] == "basic"

        # Even administrators use their own tenant default instead of seeing
        # or mutating another owner's singleton.
        assert (
            admin_client.get("/api/promotion/template-policy").json()["data"][
                "policy"
            ]
            == admin_before
        )

        invalid = operator.patch(
            "/api/promotion/template-policy",
            json={"protectionMode": "aggressive"},
        )
        assert invalid.status_code == 422

        with SessionLocal() as db:
            owner_id = db.scalar(
                select(UserAccount.id).where(
                    UserAccount.username == "template-policy-tenant"
                )
            )
            stored = db.scalar(
                select(PromotionTemplatePolicy).where(
                    PromotionTemplatePolicy.created_by == owner_id
                )
            )
            assert stored is not None
            assert stored.protection_mode == "basic"
            assert stored.devtools_action == "log"
            assert stored.lock_viewport_zoom is False
            assert stored.device_signals == "standard"
    finally:
        operator.close()
