"""The composition root: configuration and adapters wired into the app.

uvicorn starts the app with::

    uvicorn --factory --no-proxy-headers podiumd_admin.main:create_app_from_environment

``--no-proxy-headers`` matters: by default uvicorn replaces the peer address
with ``X-Forwarded-For`` when the peer is 127.0.0.1 (such as a mesh sidecar),
which would bypass ``trustedProxies``. The app resolves the client IP itself
(``podiumd_admin.adapters.http.client_ip``).

The configuration is loaded first, so a missing or invalid setting stops the
instance from starting with a ``ConfigurationError`` naming the setting.

While the app runs, two background jobs run every minute in its single
replica (design D2, ADR 0010): the expiry sweep, and the flush of the
unauthenticated-failure aggregator. At shutdown the aggregator writes what it
still holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from podiumd_admin.adapters.background import periodic_jobs
from podiumd_admin.adapters.db.readiness import database_is_reachable
from podiumd_admin.adapters.db.session_crypto import TokenCipher
from podiumd_admin.adapters.db.unit_of_work import SqlUnitOfWork
from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.auth import AuthServices, auth_settings
from podiumd_admin.adapters.logging import StdoutAuditSink, configure_logging
from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.adapters.system_clock import SystemClock
from podiumd_admin.application.authorisation import Authoriser
from podiumd_admin.application.sessions import Sessions
from podiumd_admin.application.sign_in import SignIn
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.config import Settings, load_settings


@dataclass(frozen=True, slots=True)
class _Authentication:
    services: AuthServices
    failures: UnauthenticatedFailureAggregator


def _authentication(settings: Settings, engine: AsyncEngine) -> _Authentication:
    """The authentication use cases with the real adapters."""
    sink = StdoutAuditSink()
    clock = SystemClock()
    cipher = TokenCipher([key.get_secret_value() for key in settings.session_encryption_keys])
    identity_provider = KeycloakIdentityProvider(
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret.get_secret_value(),
    )
    unit_of_work = SqlUnitOfWork(engine, sink, cipher)
    failures = UnauthenticatedFailureAggregator(sink=sink, clock=clock)
    use_case_settings = auth_settings(settings)
    services = AuthServices(
        sign_in=SignIn(
            settings=use_case_settings,
            identity_provider=identity_provider,
            unit_of_work=unit_of_work,
            audit_sink=sink,
            failures=failures,
            clock=clock,
        ),
        sessions=Sessions(
            settings=use_case_settings,
            identity_provider=identity_provider,
            unit_of_work=unit_of_work,
            audit_sink=sink,
            failures=failures,
            clock=clock,
        ),
        authoriser=Authoriser(
            settings=use_case_settings, unit_of_work=unit_of_work, audit_sink=sink, clock=clock
        ),
    )
    return _Authentication(services=services, failures=failures)


def create_app_from_environment() -> FastAPI:
    """Load the settings from the environment and build the app with real adapters."""
    settings = load_settings()
    configure_logging()
    # Connections are opened lazily, so building the app needs no database.
    engine = create_async_engine(settings.database_app_url.get_secret_value(), pool_pre_ping=True)
    authentication = _authentication(settings, engine)
    app = create_app(
        settings,
        readiness=partial(database_is_reachable, engine),
        auth=authentication.services,
    )

    async def flush_failures() -> None:
        authentication.failures.flush()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        jobs = {
            "session-expiry-sweep": authentication.services.sessions.expire_abandoned,
            "unauthenticated-failures-flush": flush_failures,
        }
        try:
            async with periodic_jobs(jobs):
                yield
        finally:
            authentication.failures.flush_all()
            await engine.dispose()

    app.router.lifespan_context = lifespan
    return app
