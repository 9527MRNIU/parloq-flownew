from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import PersonalAccount, ProtocolNode
from app.services.wa_gateway import GatewayError, WaGatewayClient


def test_protocol_node_metrics_ingress_and_marketing_controls(
    admin_client: TestClient,
) -> None:
    listed = admin_client.get("/api/protocol-nodes")
    assert listed.status_code == 200, listed.text
    node = listed.json()["data"]["rows"][0]
    definition = node["protocolDefinition"]
    assert node["id"].isdecimal()
    assert "publicId" not in node
    assert node["protocol"] == "baileys"
    assert node["accountTotal"] >= 0
    assert node["validRate"] is None or 0 <= node["validRate"] <= 100
    assert definition["name"] == "Baileys Web协议"
    assert definition["adapterKey"] == "baileys"
    assert definition["version"] == "6.7.24"
    assert definition["buildStatus"] == "ready"

    disabled_ingress = admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={
            "name": "Baileys 主节点",
            "remark": "运营主协议",
            "ingressEnabled": False,
        },
    )
    assert disabled_ingress.status_code == 200, disabled_ingress.text
    blocked = admin_client.post(
        "/api/personal-accounts",
        json={"name": "Blocked ingress", "phone": "+12025551981"},
    )
    assert blocked.status_code == 409
    assert "关闭进号" in blocked.json()["detail"]

    enabled = admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={"ingressEnabled": True},
    )
    assert enabled.status_code == 200
    created = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Protocol assigned",
            "phone": "+12025551981",
            "protocolId": node["id"],
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()["data"]["account"]
    assert account["protocol"]["id"] == node["id"]

    with SessionLocal() as db:
        stored = db.scalar(
            select(PersonalAccount).where(PersonalAccount.id == int(account["id"]))
        )
        assert stored is not None
        stored.status = "online_idle"
        stored.validation_status = "ready"
        db.commit()
    metrics = admin_client.get("/api/protocol-nodes").json()["data"]["rows"]
    current = next(row for row in metrics if row["id"] == node["id"])
    assert current["validAccounts"] >= 1
    assert current["onlineAccounts"] >= 1
    assert current["onlineRate"] <= 100
    assert admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={"marketingEnabled": False},
    ).status_code == 200
    denied_send = admin_client.post(
        f"/api/personal-accounts/{account['id']}/send",
        json={
            "to": "+12025551982",
            "message": "blocked",
            "idempotencyKey": "protocol-marketing-off-0001",
        },
    )
    assert denied_send.status_code == 409
    assert "未开启营销" in denied_send.json()["detail"]
    assert admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={"marketingEnabled": True},
    ).status_code == 200


def test_protocol_node_create_pool_and_template_contract(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/protocol-nodes",
        json={
            "name": "Landing EU partition",
            "maxAccountCount": None,
            "maxOnlineAccounts": 1000,
            "maxConcurrentPairings": None,
            "connectionPolicy": "on_demand",
            "idleDisconnectSeconds": 600,
            "postVerifyGraceSeconds": 120,
            "syncPolicy": {
                "avatar": True,
                "groupSummary": True,
                "groupDetails": False,
                "contacts": False,
                "chats": False,
                "messageHistory": False,
            },
            "rateLimitPolicy": {
                "visitorCheck": {"maxRequests": 7, "windowSeconds": 600},
                "status": {"maxRequests": 45, "windowSeconds": 60},
            },
        },
    )
    assert created.status_code == 201, created.text
    node = created.json()["data"]["protocol"]
    assert node["id"].isdecimal()
    assert node["protocolDefinition"]["version"] == "6.7.24"
    assert node["maxAccountCount"] is None
    assert node["maxOnlineAccounts"] == 1000
    assert node["connectionPolicy"] == "on_demand"
    assert node["syncPolicy"] == {
        "closeOnline": True,
        "avatar": True,
        "groupDetails": False,
        "contacts": False,
    }
    assert node["rateLimitPolicy"]["visitorCheck"] == {
        "maxRequests": 7,
        "windowSeconds": 600,
    }
    assert node["rateLimitPolicy"]["ipStart"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }
    assert node["rateLimitPolicy"]["phoneAttempt"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }
    assert node["rateLimitPolicy"]["cancel"] == {
        "maxRequests": 5,
        "windowSeconds": 600,
    }

    updated = admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={
            "syncPolicy": {
                **node["syncPolicy"],
                "closeOnline": False,
                "contacts": True,
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["protocol"]["syncPolicyVersion"] == 2
    assert updated.json()["data"]["protocol"]["syncPolicy"]["closeOnline"] is False

    rate_updated = admin_client.patch(
        f"/api/protocol-nodes/{node['id']}",
        json={
            "rateLimitPolicy": {
                "cancel": {"maxRequests": 6, "windowSeconds": 120},
                "visitorAttempt": {
                    "maxRequests": 8,
                    "windowSeconds": 900,
                },
            }
        },
    )
    assert rate_updated.status_code == 200, rate_updated.text
    updated_rate_policy = rate_updated.json()["data"]["protocol"][
        "rateLimitPolicy"
    ]
    assert updated_rate_policy["cancel"] == {
        "maxRequests": 6,
        "windowSeconds": 120,
    }
    assert updated_rate_policy["visitorAttempt"] == {
        "maxRequests": 8,
        "windowSeconds": 900,
    }
    assert updated_rate_policy["visitorCheck"]["maxRequests"] == 7

    fallback = admin_client.get("/api/protocol-nodes").json()["data"]["rows"][0]
    pool = admin_client.post(
        "/api/protocol-pools",
        json={
            "name": "Landing explicit fallback",
            "members": [
                {"protocolNodeId": node["id"], "priority": 100},
                {"protocolNodeId": fallback["id"], "priority": 200},
            ],
        },
    )
    assert pool.status_code == 201, pool.text
    pool_row = pool.json()["data"]["pool"]
    assert pool_row["id"].isdecimal()
    assert [member["protocolNodeId"] for member in pool_row["members"]] == [
        node["id"],
        fallback["id"],
    ]

    spec = admin_client.get(
        f"/api/protocol-nodes/{node['id']}/integration-spec"
    )
    assert spec.status_code == 200, spec.text
    contract = spec.json()["data"]
    assert contract["specVersion"] == "promotion-public-pairing/v1"
    assert contract["runtime"]["bridge"].startswith("window.PromotionBridge")
    assert contract["runtime"]["version"] == "promotion-browser-bridge/v2"
    assert contract["runtime"]["methods"]["status"].startswith(
        "getPairingStatus"
    )
    assert contract["status"]["tokenHeader"] == "Authorization"
    assert contract["status"]["tokenScheme"] == "Bearer"
    assert contract["status"]["successCondition"] == (
        "pairingStatus === 'verified' && verified === true"
    )
    start_body = contract["start"]["body"]
    assert "protocolId" not in start_body
    assert "sessionToken" not in start_body
    assert "deviceToken" not in start_body
    assert "visitorId" not in start_body
    assert "idempotencyKey" not in start_body
    assert start_body["deviceFingerprint"] == "thumbmarkjs-or-fallback-value"
    assert start_body["metadata"]["clientContext"]["timeZone"] == "Europe/Berlin"
    assert contract["rateLimit"]["source"] == "protocol-node"
    assert contract["rateLimit"]["policy"]["cancel"]["maxRequests"] == 6
    assert contract["rateLimit"]["response"]["status"] == 429

    referenced = admin_client.delete(f"/api/protocol-nodes/{node['id']}")
    assert referenced.status_code == 409


def test_protocol_batch_tenant_scope_and_gateway_error_summary(
    admin_client: TestClient, monkeypatch
) -> None:
    node = admin_client.get("/api/protocol-nodes").json()["data"]["rows"][0]
    created = admin_client.post(
        "/api/personal-accounts",
        json={
            "name": "Protocol batch failure",
            "phone": "+12025551983",
            "protocolId": node["id"],
        },
    )
    assert created.status_code == 201, created.text
    account_id = int(created.json()["data"]["account"]["id"])
    with SessionLocal() as db:
        protocol = db.scalar(
            select(ProtocolNode).where(ProtocolNode.id == int(node["id"]))
        )
        account = db.get(PersonalAccount, account_id)
        assert account is not None
        assert account.protocol_id == protocol.id
        account.status = "linked_offline"
        account.enabled = True
        gateway_account_id = account.gateway_account_id
        public_account_id = str(account.id)
        db.commit()

    attempted: list[str] = []

    def fail_connect(self, account_id, proxy_url=None):
        attempted.append(account_id)
        raise GatewayError("gateway connection refused")

    monkeypatch.setattr(
        WaGatewayClient,
        "connect",
        fail_connect,
    )
    response = admin_client.post(
        "/api/protocol-nodes/batch-connect", json={"protocolIds": [node["id"]]}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["failedCount"] >= 1
    assert any("gateway connection refused" in row["error"] for row in data["errors"])
    assert any(row["accountId"] == public_account_id for row in data["errors"])
    assert all("protocolPublicId" not in row for row in data["errors"])
    assert gateway_account_id in attempted
    assert public_account_id not in attempted

    missing = admin_client.post(
        "/api/protocol-nodes/batch-offline",
        json={"protocolIds": ["proto_other_tenant_or_missing"]},
    )
    assert missing.status_code == 404


def test_protocol_nodes_are_tenant_scoped(admin_client: TestClient) -> None:
    groups = admin_client.get("/api/user-groups").json()["data"]["rows"]
    operator = next(group for group in groups if group["systemKey"] == "operator")
    for username in ("protocol-tenant-a", "protocol-tenant-b"):
        created = admin_client.post(
            "/api/users",
            json={
                "username": username,
                "password": "operator-pass-123",
                "groupId": operator["id"],
            },
        )
        assert created.status_code == 201, created.text

    first = TestClient(app)
    second = TestClient(app)
    try:
        assert first.post(
            "/api/auth/login",
            json={"username": "protocol-tenant-a", "password": "operator-pass-123"},
        ).status_code == 200
        assert second.post(
            "/api/auth/login",
            json={"username": "protocol-tenant-b", "password": "operator-pass-123"},
        ).status_code == 200
        first_node = first.get("/api/protocol-nodes").json()["data"]["rows"][0]
        second_node = second.get("/api/protocol-nodes").json()["data"]["rows"][0]
        assert first_node["id"] != second_node["id"]
        assert first.patch(
            f"/api/protocol-nodes/{second_node['id']}",
            json={"name": "cross tenant"},
        ).status_code == 404
        assert second.post(
            "/api/protocol-nodes/batch-disconnect",
            json={"protocolIds": [first_node["id"]]},
        ).status_code == 404
    finally:
        first.close()
        second.close()
