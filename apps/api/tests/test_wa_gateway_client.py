from __future__ import annotations

from dataclasses import replace

from app.config import get_settings
from app.services import wa_gateway


class _Response:
    is_success = True
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self) -> dict:
        return {"data": self.data}


def test_gateway_client_uses_canonical_contract_and_bearer(monkeypatch) -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET" and url.endswith("/v1/accounts"):
            return _Response([{"id": "wa_contract", "state": "unpaired"}])
        if url.endswith("/pairing-code"):
            return _Response({"code": "1234-5678"})
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
    assert client.create("wa_contract", "+12025550199", "socks5://proxy:1080")["id"] == "wa_contract"
    assert client.get("wa_contract")["state"] == "unpaired"
    assert client.list()[0]["id"] == "wa_contract"
    assert client.update_proxy("wa_contract", None)["id"] == "wa_contract"
    assert client.import_session(
        "wa_contract", {"registered": True}, "socks5://proxy:1080"
    )["state"] == "unpaired"
    assert client.export_session("wa_contract") == {"registered": True}
    assert client.pair("wa_contract", "+12025550199", "pairing_code", None)["code"] == "1234-5678"
    assert client.send("wa_contract", "idem-12345678", "+12025550200", "hello")["status"] == "queued"

    assert calls[0][2]["json"] == {
        "id": "wa_contract",
        "phoneE164": "+12025550199",
        "proxyUrl": "socks5://proxy:1080",
    }
    assert calls[1][0] == "GET"
    assert calls[2][1].endswith("/v1/accounts")
    assert calls[3][0] == "PATCH"
    assert calls[3][2]["json"] == {"proxyUrl": ""}
    assert calls[4][1].endswith("/v1/accounts/wa_contract/import-session")
    assert calls[4][2]["json"] == {
        "session": {"registered": True},
        "proxyUrl": "socks5://proxy:1080",
    }
    assert calls[5][0] == "GET"
    assert calls[5][1].endswith("/v1/accounts/wa_contract/export-session")
    assert calls[6][1].endswith("/v1/accounts/wa_contract/pairing-code")
    assert calls[6][2]["json"] == {"phoneE164": "+12025550199"}
    assert calls[7][2]["json"] == {
        "messageId": "idem-12345678",
        "toE164": "+12025550200",
        "text": "hello",
    }
    assert all(
        call[2]["headers"]["Authorization"] == "Bearer gateway-token"
        for call in calls
    )
