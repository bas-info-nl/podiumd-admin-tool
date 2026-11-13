"""The request-time session dependency (design D2).

Spec: authentication, "Session lifetime and expiry"; access-control, "Every
request is authorised on the server". ``current_session`` resumes the Session
of the request's ``__Host-`` cookie before the handler, and so before any
authorisation: an ended Session expires here, and an expired access token is
refreshed here, so the roles are current. Without a valid Session the request
is refused with 401 ``not-signed-in`` and the cookie is cleared; the frontend
then starts a new sign-in that returns to the current page. If Keycloak
cannot be reached for a refresh, the answer is 503 and the Session is kept.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import Cookie, Depends, Request
from fastapi.responses import JSONResponse

from podiumd_admin.adapters.http.auth import SESSION_COOKIE, AuthServices, auth_services
from podiumd_admin.adapters.http.client_ip import client_ip
from podiumd_admin.adapters.http.correlation import correlation_id
from podiumd_admin.adapters.http.errors import ErrorResponse
from podiumd_admin.application.sessions import ActiveSession

NOT_SIGNED_IN: Final = "not-signed-in"
IDENTITY_PROVIDER_UNAVAILABLE: Final = "identity-provider-unavailable"


class NotSignedInError(Exception):
    """The request has no valid Session."""


async def current_session(
    services: Annotated[AuthServices, Depends(auth_services)],
    address: Annotated[str | None, Depends(client_ip)],
    correlation: Annotated[str, Depends(correlation_id)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE, max_length=255)] = None,
) -> ActiveSession:
    """The resumed Session of this request; raises ``NotSignedInError`` if there is none."""
    active = await services.sessions.resume(
        session_id, client_ip=address, correlation_id=correlation
    )
    if active is None:
        raise NotSignedInError
    return active


async def not_signed_in(_request: Request, _error: Exception) -> JSONResponse:
    """401 with a fixed code; the stale cookie is cleared."""
    response = JSONResponse(ErrorResponse(error=NOT_SIGNED_IN).model_dump(), status_code=401)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


async def identity_provider_unavailable(_request: Request, _error: Exception) -> JSONResponse:
    """503 with a fixed code: Keycloak is needed for this request but cannot be reached."""
    body = ErrorResponse(error=IDENTITY_PROVIDER_UNAVAILABLE)
    return JSONResponse(body.model_dump(), status_code=503)
