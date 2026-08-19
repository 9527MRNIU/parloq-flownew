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
            "eventRateLimitPolicy": {
                "sessionReports": {"maxRequests": 60, "windowSeconds": 60},
                "ipReports": {"maxRequests": 600, "windowSeconds": 60},
                "channelReports": {
                    "maxRequests": 10_000,
                    "windowSeconds": 60,
                },
                "metaDomainReports": {
                    "maxRequests": 5,
                    "windowSeconds": 600,
                },
            },
            "updatedAt": operator_default.json()["data"]["policy"]["updatedAt"],
        }

        updated = operator.patch(
            "/api/promotion/template-policy",
            json={
                "protectionMode": "basic",
                "devtoolsAction": "log",
                "lockViewportZoom": False,
                "deviceSignals": "standard",
                "eventRateLimitPolicy": {
                    "sessionReports": {
                        "maxRequests": 80,
                        "windowSeconds": 60,
                    },
                    "ipReports": {
                        "maxRequests": 800,
                        "windowSeconds": 60,
                    },
                    "channelReports": {
                        "maxRequests": 20_000,
                        "windowSeconds": 60,
                    },
                    "metaDomainReports": {
                        "maxRequests": 8,
                        "windowSeconds": 600,
                    },
                },
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
            "eventRateLimitPolicy": {
                "sessionReports": {"maxRequests": 80, "windowSeconds": 60},
                "ipReports": {"maxRequests": 800, "windowSeconds": 60},
                "channelReports": {
                    "maxRequests": 20_000,
                    "windowSeconds": 60,
                },
                "metaDomainReports": {
                    "maxRequests": 8,
                    "windowSeconds": 600,
                },
            },
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
        invalid_rate = operator.patch(
            "/api/promotion/template-policy",
            json={
                "eventRateLimitPolicy": {
                    "sessionReports": {
                        "maxRequests": 0,
                        "windowSeconds": 60,
                    }
                }
            },
        )
        assert invalid_rate.status_code == 422

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
            assert stored.event_rate_limit_policy_json[
                "metaDomainReports"
            ] == {"maxRequests": 8, "windowSeconds": 600}
    finally:
        operator.close()
