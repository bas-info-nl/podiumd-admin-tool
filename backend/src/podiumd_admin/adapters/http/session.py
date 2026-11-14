"""The request-time session dependency and sign-out (design D2).

Spec: authentication, "Session lifetime and expiry"; access-control, "Every
request is authorised on the server". ``current_session`` resumes the Session
of the request's ``__Host-`` cookie before the handler, and so before any
authorisation: an ended Session expires here, and an expired access token is
refreshed here, so the roles are current. Without a valid Session the request
is refused with 401 ``not-signed-in`` and the cookie is cleared; the frontend
then starts a new sign-in that returns to the current page. If Keycloak
cannot be reached for a refresh, the answer is 503 and the Session is kept.

``POST /api/v1/session/sign-out`` (spec: authentication, "Sign-out") needs a
Session, the ``X-PodiumD-Admin: 1`` header and ``session:sign-out``. A
refusal is recorded as denied (``csrf``, ``no-role`` or
``missing-permission``) and answered with 403. The ``sign-out``/``allowed``
entry is stored before the Session ends; if it cannot be stored the Session
is kept and the answer is the "action could not be recorded" error. The
answer holds Keycloak's logout URL, to which the frontend then navigates.

The CSRF check and the permission check are local to this route for now;
task group 8 replaces them with the generic CSRF guard and
``require(permission)``, built on the same ``Authoriser``.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Cookie, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from podiumd_admin.adapters.http.auth import SESSION_COOKIE, AuthServices, auth_services
from podiumd_admin.adapters.http.client_ip import client_ip
from podiumd_admin.adapters.http.correlation import correlation_id
from podiumd_admin.adapters.http.errors import ErrorResponse
from podiumd_admin.application.sessions import SIGN_OUT_ACTION, ActiveSession
from podiumd_admin.domain.authorisation import Permission

NOT_SIGNED_IN: Final = "not-signed-in"
IDENTITY_PROVIDER_UNAVAILABLE: Final = "identity-provider-unavailable"
ACCESS_DENIED: Final = "access-denied"
CSRF_HEADER: Final = "X-PodiumD-Admin"
CSRF_HEADER_VALUE: Final = "1"
SIGN_OUT_PATH: Final = "/session/sign-out"

router = APIRouter()


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


async def access_denied(_request: Request, _error: Exception) -> JSONResponse:
    """403 with a fixed code; the refusal has been recorded."""
    return JSONResponse(ErrorResponse(error=ACCESS_DENIED).model_dump(), status_code=403)


class SignOutResponse(BaseModel):
    """Where the browser goes next: Keycloak's logout, which returns to the signed-out page."""

    model_config = ConfigDict(extra="forbid")

    end_session_url: str


@router.post(
    SIGN_OUT_PATH,
    operation_id="signOut",
    response_model=SignOutResponse,
    responses={
        401: {"model": ErrorResponse, "description": "No valid session (`not-signed-in`)."},
        403: {"model": ErrorResponse, "description": "Refused and recorded (`access-denied`)."},
        500: {
            "model": ErrorResponse,
            "description": "Not recorded, so the session is kept (`action-not-recorded`).",
        },
        503: {
            "model": ErrorResponse,
            "description": "Keycloak cannot be reached (`identity-provider-unavailable`).",
        },
    },
)
async def sign_out(
    request: Request,
    services: Annotated[AuthServices, Depends(auth_services)],
    active: Annotated[ActiveSession, Depends(current_session)],
    address: Annotated[str | None, Depends(client_ip)],
    correlation: Annotated[str, Depends(correlation_id)],
    csrf: Annotated[str | None, Header(alias=CSRF_HEADER, include_in_schema=False)] = None,
) -> JSONResponse:
    """End the session; the response holds Keycloak's logout URL."""
    target = f"{request.method} {request.url.path}"
    if csrf != CSRF_HEADER_VALUE:
        await services.authoriser.refuse_cross_site(
            active,
            action=SIGN_OUT_ACTION,
            target=target,
            client_ip=address,
            correlation_id=correlation,
        )
    await services.authoriser.require(
        active,
        Permission.SESSION_SIGN_OUT,
        action=SIGN_OUT_ACTION,
        target=target,
        client_ip=address,
        correlation_id=correlation,
    )
    url = await services.sessions.sign_out(active, client_ip=address, correlation_id=correlation)
    response = JSONResponse(SignOutResponse(end_session_url=url).model_dump())
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
