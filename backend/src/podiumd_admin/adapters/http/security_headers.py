"""Security headers on every response (design D2, "Response hardening").

Spec: installation, "Hardened runtime and responses". A plain ASGI middleware,
so it also covers error responses, 404s and streamed responses. It replaces
any value a handler set, so each header appears exactly once.
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
)
_EVERY_RESPONSE: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_API_PREFIX: Final = "/api"


def _is_api(path: str) -> bool:
    return path == _API_PREFIX or path.startswith(f"{_API_PREFIX}/")


class SecurityHeadersMiddleware:
    """Adds the CSP, nosniff and Referrer-Policy headers; ``no-store`` on the API."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        api = _is_api(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _EVERY_RESPONSE.items():
                    headers[name] = value
                if api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
