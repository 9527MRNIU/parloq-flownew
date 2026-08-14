from __future__ import annotations

from unittest.mock import MagicMock, Mock

from app.services import domain_verify


def test_proxied_domain_can_prove_application_routing(monkeypatch) -> None:
    def dns_answers(name: str, record_type: str, _timeout: float) -> list[str]:
        if record_type == "TXT":
            return ['"parloq-verification=proof-token"']
        if record_type == "CNAME":
            return []
        raise AssertionError((name, record_type))

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "hostname": "landing.example",
            "proof": "parloq-domain-routing-v1",
        }
    }
    monkeypatch.setattr(domain_verify, "_dns_answers", dns_answers)
    monkeypatch.setattr(domain_verify.httpx, "get", Mock(return_value=response))
    monkeypatch.setattr(
        domain_verify.socket,
        "getaddrinfo",
        Mock(return_value=[(2, 1, 6, "", ("1.1.1.1", 443))]),
    )
    wrapped = Mock()
    context = Mock()
    context.wrap_socket.return_value = MagicMock()
    context.wrap_socket.return_value.__enter__.return_value = wrapped
    monkeypatch.setattr(domain_verify.ssl, "create_default_context", Mock(return_value=context))
    raw_socket = MagicMock()
    raw_socket.__enter__.return_value = raw_socket
    raw_socket.__exit__.return_value = False
    monkeypatch.setattr(domain_verify.socket, "create_connection", Mock(return_value=raw_socket))

    domain_verify.verify_public_domain(
        "landing.example",
        verification_name="_parloq-verify.landing.example",
        verification_value="parloq-verification=proof-token",
        cname_target="center.parloq.com",
        routing_probe_path="/api/domains/public-verification/proof-token",
    )

    domain_verify.httpx.get.assert_called_once_with(
        "https://landing.example/api/domains/public-verification/proof-token",
        timeout=5.0,
        follow_redirects=False,
    )
