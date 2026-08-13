from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import PromotionTemplatePolicy


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
    admin_default = admin_client.get("/api/promotion/template-policy")
    assert admin_default.status_code == 200, admin_default.text
    admin_policy = admin_default.json()["data"]["policy"]
    assert {key: value for key, value in admin_policy.items() if key != "updatedAt"} == {
        "protectionMode": "basic",
        "devtoolsAction": "log",
        "lockViewportZoom": False,
        "deviceSignals": "standard",
    }

    _create_operator(admin_client, "template-policy-tenant")
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
        assert operator_default.json()["data"]["policy"]["protectionMode"] == "basic"

        updated = operator.patch(
            "/api/promotion/template-policy",
            json={
                "protectionMode": "strict",
                "devtoolsAction": "blank",
                "lockViewportZoom": True,
                "deviceSignals": "enhanced",
            },
        )
        assert updated.status_code == 200, updated.text
        updated_policy = updated.json()["data"]["policy"]
        assert {key: value for key, value in updated_policy.items() if key != "updatedAt"} == {
            "protectionMode": "strict",
            "devtoolsAction": "blank",
            "lockViewportZoom": True,
            "deviceSignals": "enhanced",
        }
        assert operator.get("/api/promotion/template-policy").json()["data"][
            "policy"
        ]["protectionMode"] == "strict"

        # Even administrators use their own tenant default instead of seeing
        # or mutating another owner's singleton.
        assert admin_client.get("/api/promotion/template-policy").json()["data"][
            "policy"
        ]["protectionMode"] == "basic"

        invalid = operator.patch(
            "/api/promotion/template-policy",
            json={"protectionMode": "aggressive"},
        )
        assert invalid.status_code == 422

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(PromotionTemplatePolicy).order_by(
                        PromotionTemplatePolicy.created_by
                    )
                ).all()
            )
            assert len(rows) == 2
            assert {row.protection_mode for row in rows} == {"basic", "strict"}
    finally:
        operator.close()
