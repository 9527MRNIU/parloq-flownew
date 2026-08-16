from __future__ import annotations

import re

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_PAIRING_ACTION = re.compile(
    r"^/api/public/promotion/channels/[^/]+/pairing/[^/]+/(?:status|cancel)$"
)


class PublicPairingCorsMiddleware:
    """Allow only token-protected pairing calls from the public CSP sandbox.

    Public templates intentionally run without ``allow-same-origin``. Their
    browser origin is therefore the opaque value ``null`` and the custom
    standard Authorization header triggers a CORS preflight. The global management CORS
    policy must not trust every opaque origin, so this exception is constrained
    to the two public pairing endpoints and the one non-sensitive header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        origin = headers.get(b"origin", b"")
        requested_method = headers.get(b"access-control-request-method", b"").upper()
        requested_headers = {
            item.strip().lower()
            for item in headers.get(b"access-control-request-headers", b"").split(b",")
            if item.strip()
        }
        if (
            origin == b"null"
            and _PAIRING_ACTION.fullmatch(path)
            and requested_method in {b"GET", b"POST"}
            and requested_headers.issubset({b"authorization"})
        ):
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "null",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
