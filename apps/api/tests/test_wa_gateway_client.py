from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import get_settings
from app.services import wa_gateway


class _Response:
    is_success = True
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self) -> dict:
        return {"data": self.data}


def test_gateway_error_preserves_response_status(monkeypatch) -> None:
    response = _Response({})
    response.is_success = False
    response.status_code = 404
    monkeypatch.setattr(
        wa_gateway._HTTP_CLIENT,
        "request",
        lambda *_args, **_kwargs: response,
    )
    client = wa_gateway.WaGatewayClient()
    client.settings = replace(
        get_settings(),
        wa_gateway_mock=False,
        wa_gateway_url="http://gateway.test",
    )

    with pytest.raises(wa_gateway.GatewayError) as caught:
        client.update_proxy("wa_missing", None)

    assert caught.value.status_code == 404
    assert str(caught.value) == "WhatsApp 网关请求失败（404）"


def test_gateway_error_preserves_sanitized_failure_detail(monkeypatch) -> None:
    response = _Response({})
    response.is_success = False
    response.status_code = 502
    response.json = lambda: {
        "error": {
            "code": "protocol_error",
            "message": "pairing failed",
            "failure": {
                "code": "proxy_authentication_failed",
                "title": "代理认证失败",
                "message": "账号连接线路拒绝了当前认证信息。",
                "suggestion": "请更换代理后重试。",
                "stage": "connection_route",
                "retryable": True,
                "technicalMessage": (
                    "connect socks5://user:secret@proxy.example failed"
                ),
            },
        }
    }
    monkeypatch.setattr(
        wa_gateway._HTTP_CLIENT,
        "request",
        lambda *_args, **_kwargs: response,
    )
    client = wa_gateway.WaGatewayClient()
    client.settings = replace(
        get_settings(),
        wa_gateway_mock=False,
        wa_gateway_url="http://gateway.test",
    )

    with pytest.raises(wa_gateway.GatewayError) as caught:
        client.update_proxy("wa_failure", None)

    assert caught.value.failure_detail["code"] == "proxy_authentication_failed"
    assert "user:secret" not in caught.value.failure_detail["technicalMessage"]
    assert "[REDACTED]" in caught.value.failure_detail["technicalMessage"]


def test_gateway_client_uses_canonical_contract_and_bearer(monkeypatch) -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET" and url.endswith("/v1/accounts"):
            return _Response([{"id": "wa_contract", "state": "unpaired"}])
        if method == "GET" and url.endswith("/v1/protocol-info"):
            return _Response(
                {
                    "protocol": "baileys",
                    "name": "Baileys Web",
                    "baileysVersion": "6.7.24",
                    "currentWaWebVersion": "2.3000.1",
                    "latestWaWebVersion": "2.3000.2",
                    "versionStatus": "update_available",
                }
            )
        if url.endswith("/pairing-code"):
            return _Response({"code": "1234-5678"})
        if url.endswith("/reauthentication-code"):
            return _Response({"code": "8765-4321"})
        if url.endswith("/metadata-sync"):
            return _Response({"metadataSyncStatus": "ready", "quality": {}})
        if url.endswith("/messages"):
            return _Response({"messageId": "idem-12345678", "status": "queued"})
        if url.endswith("/export-session"):
            return _Response({"session": {"registered": True}})
        return _Response({"id": "wa_contract", "state": "unpaired"})

    monkeypatch.setattr(wa_gateway._HTTP_CLIENT, "request", request)
    client = wa_gateway.WaGatewayClient()
    client.settings = replace(
        get_settings(),
        wa_gateway_mock=False,
        wa_gateway_url="http://gateway.test",
        wa_gateway_api_token="gateway-token",
    )
    assert client.create(
        "wa_contract",
        "+12025550199",
        "socks5://proxy:1080",
        protocol_definition_id="8541455568736000",
        protocol_version="6.7.24",
    )["id"] == "wa_contract"
    assert client.get("wa_contract")["state"] == "unpaired"
    assert client.list()[0]["id"] == "wa_contract"
    assert client.protocol_info()["baileysVersion"] == "6.7.24"
    assert client.update_proxy("wa_contract", None)["id"] == "wa_contract"
    assert client.import_session(
        "wa_contract",
        {"registered": True},
        "socks5://proxy:1080",
        protocol_definition_id="8541455568736000",
        protocol_version="6.7.24",
    )["state"] == "unpaired"
    assert client.export_session("wa_contract") == {"registered": True}
    assert client.pair("wa_contract", "+12025550199", "pairing_code", None)["code"] == "1234-5678"
    assert client.cancel_pairing("wa_contract")["state"] == "unpaired"
    assert client.send("wa_contract", "idem-12345678", "+12025550200", "hello")["status"] == "queued"
    structured_message = {
        "version": 1,
        "header": {"type": "none"},
        "body": {"text": "hello"},
        "footer": {"text": ""},
        "buttons": [{"type": "quick_reply", "text": "Reply", "id": "reply"}],
    }
    assert client.send(
        "wa_contract", "idem-structured", "+12025550200", structured_message
    )["status"] == "queued"
    assert client.reauthenticate("wa_contract", "+12025550199")["code"] == "8765-4321"
    assert client.sync_metadata("wa_contract", {"avatar": True})[
        "metadataSyncStatus"
    ] == "ready"

    assert calls[0][2]["json"] == {
        "id": "wa_contract",
        "protocolDefinitionId": "8541455568736000",
        "protocolVersion": "6.7.24",
        "phoneE164": "+12025550199",
        "proxyUrl": "socks5://proxy:1080",
    }
    assert calls[1][0] == "GET"
    assert calls[2][1].endswith("/v1/accounts")
    assert calls[3][1].endswith("/v1/protocol-info")
    assert calls[4][0] == "PATCH"
    assert calls[4][2]["json"] == {"proxyUrl": ""}
    assert calls[5][1].endswith("/v1/accounts/wa_contract/import-session")
    assert calls[5][2]["json"] == {
        "session": {"registered": True},
        "proxyUrl": "socks5://proxy:1080",
        "protocolDefinitionId": "8541455568736000",
        "protocolVersion": "6.7.24",
    }
    assert calls[6][0] == "GET"
    assert calls[6][1].endswith("/v1/accounts/wa_contract/export-session")
    assert calls[7][1].endswith("/v1/accounts/wa_contract/pairing-code")
    assert calls[7][2]["json"] == {"phoneE164": "+12025550199"}
    assert calls[8][1].endswith("/v1/accounts/wa_contract/pairing-cancel")
    assert calls[9][2]["json"] == {
        "messageId": "idem-12345678",
        "toE164": "+12025550200",
        "text": "hello",
    }
    assert calls[10][2]["json"] == {
        "messageId": "idem-structured",
        "toE164": "+12025550200",
        "message": structured_message,
    }
    assert calls[11][1].endswith(
        "/v1/accounts/wa_contract/reauthentication-code"
    )
    assert calls[11][2]["json"] == {"phoneE164": "+12025550199"}
    assert calls[12][1].endswith("/v1/accounts/wa_contract/metadata-sync")
    assert calls[12][2]["json"] == {"syncPolicy": {"avatar": True}}
    assert all(
        call[2]["headers"]["Authorization"] == "Bearer gateway-token"
        for call in calls
    )


def test_connect_synchronizes_an_explicit_proxy_before_connecting(monkeypatch) -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response({"id": "wa_connect", "state": "online_idle"})

    monkeypatch.setattr(wa_gateway._HTTP_CLIENT, "request", request)
    client = wa_gateway.WaGatewayClient()
    client.settings = replace(
        get_settings(),
        wa_gateway_mock=False,
        wa_gateway_url="http://gateway.test",
        wa_gateway_api_token="gateway-token",
    )

    result = client.connect("wa_connect", "socks5://proxy.test:1080")

    assert result["state"] == "online_idle"
    assert [(method, url.rsplit("/", 1)[-1]) for method, url, _ in calls] == [
        ("PATCH", "wa_connect"),
        ("POST", "connect"),
    ]
    assert calls[0][2]["json"] == {"proxyUrl": "socks5://proxy.test:1080"}

    calls.clear()
    client.connect("wa_connect")
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/v1/accounts/wa_connect/connect")
