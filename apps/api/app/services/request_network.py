from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re

from starlette.requests import Request


_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_NON_COUNTRY_CODES = {"XX"}


@dataclass(frozen=True, slots=True)
class RequestNetwork:
    source_ip: str | None
    visitor_country_code: str | None
    network_source: str | None


def _ip(value: str | None) -> str | None:
    try:
        return ipaddress.ip_address(str(value or "").strip()).compressed
    except ValueError:
        return None


def _trusted_proxy_peer(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        peer = ipaddress.ip_address(request.client.host.strip())
    except ValueError:
        return False
    return peer.is_private or peer.is_loopback or peer.is_link_local


def _cloudflare_country(request: Request) -> str | None:
    value = request.headers.get("CF-IPCountry", "").strip().upper()
    if not _COUNTRY_CODE.fullmatch(value) or value in _NON_COUNTRY_CODES:
        return None
    return value


def resolve_request_network(request: Request) -> RequestNetwork:
    """Resolve a server-trusted network snapshot for a public request.

    Production public traffic reaches the API through the private web proxy, so
    forwarded headers are considered only when the direct peer is private or
    loopback. Cloudflare's connecting IP is preferred because managed promotion
    domains are proxied by Cloudflare. The request body is never consulted.
    """

    if _trusted_proxy_peer(request):
        cloudflare_ip = _ip(request.headers.get("CF-Connecting-IP"))
        if cloudflare_ip:
            return RequestNetwork(
                source_ip=cloudflare_ip,
                visitor_country_code=_cloudflare_country(request),
                network_source="cloudflare",
            )

        real_ip = _ip(request.headers.get("X-Real-IP"))
        if real_ip:
            return RequestNetwork(real_ip, None, "proxy")

        forwarded = request.headers.get("X-Forwarded-For", "")
        for candidate in reversed(forwarded.split(",")):
            forwarded_ip = _ip(candidate)
            if forwarded_ip and ipaddress.ip_address(forwarded_ip).is_global:
                return RequestNetwork(forwarded_ip, None, "proxy")

    peer_ip = _ip(request.client.host if request.client else None)
    return RequestNetwork(
        source_ip=peer_ip,
        visitor_country_code=None,
        network_source="peer" if peer_ip else None,
    )
