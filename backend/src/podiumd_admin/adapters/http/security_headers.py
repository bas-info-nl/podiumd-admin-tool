"""Security headers on every response (design D2, "Response hardening").

Spec: installation, "Hardened runtime and responses". A plain ASGI middleware,
so it also covers error responses, 404s and streamed responses. It replaces
any value a handler set, so each header appears exactly once.

Starlette answers an unhandled error in ``ServerErrorMiddleware``, which runs
outside every user middleware, so its 500 would carry none of these headers.
This middleware therefore answers such an error itself, with a fixed body and
no detail, and re-raises it, so the server still logs it.
"""

from __future__ import annotations

import json
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
INTERNAL_ERROR: Final = "internal-error"
_INTERNAL_ERROR_BODY: Final = json.dumps({"error": INTERNAL_ERROR}).encode()


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
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in _EVERY_RESPONSE.items():
                    headers[name] = value
                if api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if not started:
                await _send_internal_error(send_with_headers)
            raise


async def _send_internal_error(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_INTERNAL_ERROR_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _INTERNAL_ERROR_BODY})
