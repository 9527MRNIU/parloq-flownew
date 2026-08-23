from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request

from app.services.request_network import RequestNetwork


def _header(request: Request, name: str, limit: int) -> str | None:
    value = request.headers.get(name, "").strip()
    return value[:limit] or None


def _forwarded_host(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    return (forwarded or request.headers.get("host", "").strip())[:255] or None


def _preferred_language(accept_language: str | None) -> str | None:
    first = str(accept_language or "").split(",", 1)[0].split(";", 1)[0].strip()
    return first[:64] or None


def public_request_context(
    request: Request,
    network: RequestNetwork,
    *,
    received_at: datetime | None = None,
) -> dict[str, str]:
    """Build the server-owned context for one public browser request.

    Client JSON is deliberately not consulted. Reverse-proxy network values are
    accepted only after ``resolve_request_network`` has validated their source.
    """

    accept_language = _header(request, "accept-language", 512)
    values = {
        "userAgent": _header(request, "user-agent", 1000),
        "language": _preferred_language(accept_language),
        "acceptLanguage": accept_language,
        "referrer": _header(request, "referer", 2048),
        "origin": _header(request, "origin", 512),
        "host": _forwarded_host(request),
        "requestPath": request.url.path[:2048],
        "requestMethod": request.method,
        "sourceIp": network.source_ip,
        "countryCode": network.visitor_country_code,
        "networkSource": network.network_source,
        "receivedAt": (received_at or datetime.now(UTC)).isoformat(),
    }
    return {key: value for key, value in values.items() if value}
