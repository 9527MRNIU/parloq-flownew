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
    assert node["protocol"] == "baileys"
    assert node["accountTotal"] >= 0
    assert node["validRate"] is None or 0 <= node["validRate"] <= 100

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
    assert "允许进号" in blocked.json()["detail"]

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
            select(PersonalAccount).where(PersonalAccount.public_id == account["id"])
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


def test_protocol_batch_tenant_scope_and_gateway_error_summary(
    admin_client: TestClient, monkeypatch
) -> None:
    node = admin_client.get("/api/protocol-nodes").json()["data"]["rows"][0]
    with SessionLocal() as db:
        protocol = db.scalar(
            select(ProtocolNode).where(ProtocolNode.public_id == node["id"])
        )
        account = db.scalar(
            select(PersonalAccount).where(
                PersonalAccount.protocol_id == protocol.id,
                PersonalAccount.archived_at.is_(None),
            )
        )
        assert account is not None
        account.status = "linked_offline"
        account.enabled = True
        db.commit()

    monkeypatch.setattr(
        WaGatewayClient,
        "connect",
        lambda self, account_id, proxy_url=None: (_ for _ in ()).throw(
            GatewayError("gateway connection refused")
        ),
    )
    response = admin_client.post(
        "/api/protocol-nodes/batch-connect", json={"protocolIds": [node["id"]]}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["failedCount"] >= 1
    assert any("gateway connection refused" in row["error"] for row in data["errors"])

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
