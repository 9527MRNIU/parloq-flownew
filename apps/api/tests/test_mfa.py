from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.services.mfa import totp_code, totp_counter


def test_totp_matches_rfc_6238_sha1_vector() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    at = datetime.fromtimestamp(59, tz=UTC)

    assert totp_code(secret, at=at) == "287082"


def test_optional_mfa_login_recovery_and_admin_reset(admin_client: TestClient) -> None:
    groups = admin_client.get("/api/system/roles").json()["data"]["rows"]
    operator_group = next(row for row in groups if row["systemKey"] == "operator")
    created = admin_client.post(
        "/api/users",
        json={
            "username": "mfa-flow-user",
            "password": "mfa-flow-password-123",
            "groupId": operator_group["id"],
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["user"]["id"]

    try:
        with TestClient(app) as operator:
            login = operator.post(
                "/api/auth/login",
                json={"username": "mfa-flow-user", "password": "mfa-flow-password-123"},
            )
            assert login.status_code == 200
            assert login.json()["data"]["mfaRequired"] is False
            assert operator.get("/api/auth/mfa/status").json()["data"]["enabled"] is False

            wrong_password = operator.post(
                "/api/auth/mfa/setup", json={"currentPassword": "wrong-password"}
            )
            assert wrong_password.status_code == 401

            setup = operator.post(
                "/api/auth/mfa/setup",
                json={"currentPassword": "mfa-flow-password-123"},
            )
            assert setup.status_code == 200, setup.text
            secret = setup.json()["data"]["secret"]
            assert setup.json()["data"]["otpauthUri"].startswith("otpauth://totp/")

            setup_code = totp_code(secret, counter=totp_counter() - 1)
            confirmed = operator.post(
                "/api/auth/mfa/setup/confirm", json={"code": setup_code}
            )
            assert confirmed.status_code == 200, confirmed.text
            recovery_codes = confirmed.json()["data"]["recoveryCodes"]
            assert len(recovery_codes) == 10
            assert operator.get("/api/auth/me").json()["data"]["user"]["mfaEnabled"] is True

            assert operator.post("/api/auth/logout").status_code == 200
            challenged = operator.post(
                "/api/auth/login",
                json={"username": "mfa-flow-user", "password": "mfa-flow-password-123"},
            )
            assert challenged.status_code == 200
            challenge_data = challenged.json()["data"]
            assert challenge_data["mfaRequired"] is True
            assert "user" not in challenge_data
            assert operator.get("/api/auth/me").status_code == 401

            invalid_code = operator.post(
                "/api/auth/mfa/login/verify",
                json={
                    "challengeToken": challenge_data["challengeToken"],
                    "code": "not-a-code",
                },
            )
            assert invalid_code.status_code == 401

            current_code = totp_code(secret)
            verified = operator.post(
                "/api/auth/mfa/login/verify",
                json={
                    "challengeToken": challenge_data["challengeToken"],
                    "code": current_code,
                },
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["data"]["user"]["username"] == "mfa-flow-user"
            reused = operator.post(
                "/api/auth/mfa/login/verify",
                json={
                    "challengeToken": challenge_data["challengeToken"],
                    "code": current_code,
                },
            )
            assert reused.status_code == 401

            assert operator.post("/api/auth/logout").status_code == 200
            recovery_challenge = operator.post(
                "/api/auth/login",
                json={"username": "mfa-flow-user", "password": "mfa-flow-password-123"},
            ).json()["data"]
            recovered = operator.post(
                "/api/auth/mfa/login/verify",
                json={
                    "challengeToken": recovery_challenge["challengeToken"],
                    "code": recovery_codes[0],
                },
            )
            assert recovered.status_code == 200, recovered.text
            status_payload = operator.get("/api/auth/mfa/status").json()["data"]
            assert status_payload["recoveryCodesRemaining"] == 9

            reset = admin_client.post(f"/api/users/{user_id}/mfa/reset")
            assert reset.status_code == 200, reset.text
            assert reset.json()["data"]["reset"] is True
            assert operator.get("/api/auth/me").status_code == 401

            normal_login = operator.post(
                "/api/auth/login",
                json={"username": "mfa-flow-user", "password": "mfa-flow-password-123"},
            )
            assert normal_login.status_code == 200
            assert normal_login.json()["data"]["mfaRequired"] is False
    finally:
        deleted = admin_client.delete(f"/api/users/{user_id}")
        assert deleted.status_code == 200, deleted.text
