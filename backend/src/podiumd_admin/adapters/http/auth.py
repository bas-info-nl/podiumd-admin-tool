"""Sign-in, the OIDC callback and back-channel logout (design D2).

Spec: authentication, "Sign-in through the Environment's Keycloak", "Safe
return after sign-in and sign-out" and "Sessions are held by the server".

These routes are on the unauthenticated allowlist (access-control, "Every
request is authorised on the server") and stay out of the OpenAPI document:
the browser navigates to them, the generated client never calls them.

Every absolute URL sent to Keycloak is built from ``publicHostname``, never
from the ``Host`` or ``X-Forwarded-Host`` header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from podiumd_admin.adapters.http.context import AppContext, app_context
from podiumd_admin.adapters.http.correlation import correlation_id
from podiumd_admin.application.authentication import AuthSettings
from podiumd_admin.application.sessions import Sessions
from podiumd_admin.application.sign_in import SignIn
from podiumd_admin.config import Settings
from podiumd_admin.domain.sign_in import MAX_RETURN_PATH_LENGTH, SIGN_IN_ATTEMPT_LIFETIME
from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError

CALLBACK_PATH: Final = "/auth/callback"
SIGNED_OUT_PATH: Final = "/signed-out"
SIGN_IN_ERROR_PATH: Final = "/sign-in-error"
NO_ACCESS_PATH: Final = "/no-access"

SESSION_COOKIE: Final = "__Host-podiumd_admin_session"
SIGN_IN_COOKIE: Final = "__Host-podiumd_admin_sign_in"

router = APIRouter(prefix="/auth", include_in_schema=False)


@dataclass(frozen=True, slots=True)
class AuthServices:
    """The authentication use cases the routes call."""

    sign_in: SignIn
    sessions: Sessions


def public_url(settings: Settings, path: str) -> str:
    """An absolute URL of this Admin Tool Instance, from the configured hostname only."""
    return f"https://{settings.public_hostname}{path}"


def auth_settings(settings: Settings) -> AuthSettings:
    """The settings of the authentication use cases, built from the configuration."""
    return AuthSettings(
        environment=settings.environment,
        role_mapping=settings.role_mapping,
        timeouts=settings.session_timeouts,
        redirect_uri=public_url(settings, CALLBACK_PATH),
        post_logout_redirect_uri=public_url(settings, SIGNED_OUT_PATH),
    )


def auth_services(context: Annotated[AppContext, Depends(app_context)]) -> AuthServices:
    """The authentication use cases the app was built with."""
    if context.auth is None:  # pragma: no cover - create_app_from_environment always wires them
        raise RuntimeError("the app was built without authentication")
    return context.auth


def _redirect(location: str) -> RedirectResponse:
    response = RedirectResponse(location, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


def _page(path: str, **query: str) -> RedirectResponse:
    """A redirect to a page of the frontend, on this host."""
    return _redirect(f"{path}?{urlencode(query)}" if query else path)


def set_cookie(response: RedirectResponse, name: str, value: str, max_age: int | None) -> None:
    """A ``__Host-`` cookie: Secure, ``Path=/``, no ``Domain``; HttpOnly and SameSite=Lax."""
    response.set_cookie(
        name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite="lax"
    )


@router.get("/sign-in")
async def sign_in(
    services: Annotated[AuthServices, Depends(auth_services)],
    correlation: Annotated[str, Depends(correlation_id)],
    return_to: Annotated[str | None, Query(max_length=MAX_RETURN_PATH_LENGTH * 2)] = None,
) -> RedirectResponse:
    """Start a sign-in and send the browser to Keycloak."""
    try:
        started = await services.sign_in.start(return_to)
    except IdentityProviderUnavailableError:
        return _page(SIGN_IN_ERROR_PATH, correlation_id=correlation)
    response = _redirect(started.authorization_url)
    set_cookie(
        response,
        SIGN_IN_COOKIE,
        started.attempt_id,
        max_age=int(SIGN_IN_ATTEMPT_LIFETIME.total_seconds()),
    )
    return response
