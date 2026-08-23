from __future__ import annotations

from starlette.requests import Request

from app.services.request_context import public_request_context
from app.services.request_network import resolve_request_network


def _request(
    *,
    client: tuple[str, int],
    headers: dict[str, str] | None = None,
    path: str = "/",
    method: str = "GET",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in (headers or {}).items()
            ],
            "client": client,
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_cloudflare_network_headers_are_used_behind_private_proxy() -> None:
    value = resolve_request_network(
        _request(
            client=("172.18.0.4", 42000),
            headers={
                "CF-Connecting-IP": "2001:4860:4860::8888",
                "CF-IPCountry": "ca",
                "X-Real-IP": "192.0.2.7",
            },
        )
    )

    assert value.source_ip == "2001:4860:4860::8888"
    assert value.visitor_country_code == "CA"
    assert value.network_source == "cloudflare"


def test_cloudflare_network_headers_survive_uvicorn_public_peer_rewrite() -> None:
    value = resolve_request_network(
        _request(
            client=("104.194.82.11", 42000),
            headers={
                "CF-Connecting-IP": "104.194.82.11",
                "CF-IPCountry": "us",
                "X-Real-IP": "104.23.251.226",
                "X-Forwarded-For": "104.194.82.11, 104.23.251.226",
            },
        )
    )

    assert value.source_ip == "104.194.82.11"
    assert value.visitor_country_code == "US"
    assert value.network_source == "cloudflare"


def test_mismatched_spoofed_forwarding_headers_are_ignored_for_public_peer() -> None:
    value = resolve_request_network(
        _request(
            client=("8.8.8.8", 42000),
            headers={
                "CF-Connecting-IP": "1.1.1.1",
                "CF-IPCountry": "US",
                "X-Real-IP": "9.9.9.9",
            },
        )
    )

    assert value.source_ip == "8.8.8.8"
    assert value.visitor_country_code is None
    assert value.network_source == "peer"


def test_cloudflare_non_country_codes_are_not_persisted() -> None:
    value = resolve_request_network(
        _request(
            client=("1.1.1.1", 42000),
            headers={
                "CF-Connecting-IP": "1.1.1.1",
                "CF-IPCountry": "XX",
            },
        )
    )

    assert value.source_ip == "1.1.1.1"
    assert value.visitor_country_code is None
    assert value.network_source == "cloudflare"


def test_proxy_ip_fallback_does_not_invent_a_country() -> None:
    value = resolve_request_network(
        _request(
            client=("127.0.0.1", 42000),
            headers={"X-Forwarded-For": "8.8.4.4, 172.18.0.4"},
        )
    )

    assert value.source_ip == "8.8.4.4"
    assert value.visitor_country_code is None
    assert value.network_source == "proxy"


def test_public_request_context_uses_headers_and_trusted_network_snapshot() -> None:
    request = _request(
        client=("172.18.0.4", 42000),
        method="POST",
        path="/api/public/promotion/channels/demo/events",
        headers={
            "Host": "landing.example",
            "X-Forwarded-Host": "promo.example",
            "User-Agent": "Browser/123",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://promo.example/demo",
            "Origin": "https://promo.example",
            "CF-Connecting-IP": "1.1.1.1",
            "CF-IPCountry": "AU",
        },
    )
    network = resolve_request_network(request)

    context = public_request_context(request, network)

    assert context["userAgent"] == "Browser/123"
    assert context["language"] == "zh-CN"
    assert context["acceptLanguage"] == "zh-CN,zh;q=0.9"
    assert context["host"] == "promo.example"
    assert context["requestMethod"] == "POST"
    assert context["requestPath"].endswith("/demo/events")
    assert context["sourceIp"] == "1.1.1.1"
    assert context["countryCode"] == "AU"
    assert context["networkSource"] == "cloudflare"
    assert context["receivedAt"]
