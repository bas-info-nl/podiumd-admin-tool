"""The FastAPI app factory (design D1, D2, D7).

``create_app`` builds the app for one configuration: the API under
``/api/v1``, the health endpoints, the security-headers middleware and the
error handlers. FastAPI's interactive docs, ReDoc and OpenAPI URLs are
disabled at runtime; the OpenAPI document is exported at build time instead
(``podiumd_admin.adapters.http.openapi``).
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from podiumd_admin import __version__
from podiumd_admin.adapters.db.unit_of_work import TransactionAbortedError
from podiumd_admin.adapters.http import auth, environment, health, session
from podiumd_admin.adapters.http.auth import AuthServices
from podiumd_admin.adapters.http.context import AppContext, ReadinessCheck
from podiumd_admin.adapters.http.errors import ACTION_NOT_RECORDED, ErrorResponse
from podiumd_admin.adapters.http.security_headers import SecurityHeadersMiddleware
from podiumd_admin.adapters.http.session import (
    NotSignedInError,
    access_denied,
    identity_provider_unavailable,
    not_signed_in,
)
from podiumd_admin.application.audit import AuditWriteFailedError
from podiumd_admin.application.authorisation import AccessDeniedError
from podiumd_admin.config import Settings
from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError

API_PREFIX: Final = "/api/v1"
TITLE: Final = "PodiumD Admin Tool"


async def _action_not_recorded(_request: Request, _error: Exception) -> JSONResponse:
    """Spec audit-log, "No action without an Audit Entry"; issue #30.

    The action did not take effect because its Audit Entry could not be
    stored, or its transaction was rolled back. No internal detail is sent.
    """
    body = ErrorResponse(error=ACTION_NOT_RECORDED)
    return JSONResponse(body.model_dump(), status_code=500)


def build_app() -> FastAPI:
    """The app's routes, middleware and handlers, without a configuration.

    Used by ``create_app`` and by the OpenAPI export, which needs no settings.
    """
    app = FastAPI(
        title=TITLE,
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(environment.router)
    api.include_router(session.router)
    app.include_router(api)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(AuditWriteFailedError, _action_not_recorded)
    app.add_exception_handler(TransactionAbortedError, _action_not_recorded)
    app.add_exception_handler(NotSignedInError, not_signed_in)
    app.add_exception_handler(AccessDeniedError, access_denied)
    app.add_exception_handler(IdentityProviderUnavailableError, identity_provider_unavailable)
    return app


def create_app(
    settings: Settings, *, readiness: ReadinessCheck, auth: AuthServices | None = None
) -> FastAPI:
    """The app for ``settings``.

    ``readiness`` tells whether the database is reachable; ``auth`` holds the
    authentication use cases.
    """
    app = build_app()
    app.state.context = AppContext(settings=settings, readiness=readiness, auth=auth)
    return app
