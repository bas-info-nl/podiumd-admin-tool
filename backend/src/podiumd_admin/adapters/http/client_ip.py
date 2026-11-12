"""The client IP of a request, as recorded in Audit Entries (task 6.4).

Spec: installation, "Trusted proxies". ``X-Forwarded-For`` is honoured only
when the connecting peer is in ``trustedProxies``; see
``podiumd_admin.domain.client_ip``. Never raises on a malformed header.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from podiumd_admin.adapters.http.context import AppContext, app_context
from podiumd_admin.domain.client_ip import resolve_client_ip


def client_ip(request: Request, context: Annotated[AppContext, Depends(app_context)]) -> str | None:
    """The address of the nearest client that is not a trusted proxy, or ``None``."""
    peer = request.client.host if request.client is not None else None
    return resolve_client_ip(
        peer,
        request.headers.getlist("x-forwarded-for"),
        trusted_proxies=context.settings.trusted_proxies,
    )
