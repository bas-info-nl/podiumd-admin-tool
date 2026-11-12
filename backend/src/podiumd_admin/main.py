"""The composition root: configuration and adapters wired into the app.

uvicorn starts the app with::

    uvicorn --factory --no-proxy-headers podiumd_admin.main:create_app_from_environment

``--no-proxy-headers`` matters: by default uvicorn replaces the peer address
with ``X-Forwarded-For`` when the peer is 127.0.0.1 (such as a mesh sidecar),
which would bypass ``trustedProxies``. The app resolves the client IP itself
(``podiumd_admin.adapters.http.client_ip``).

The configuration is loaded first, so a missing or invalid setting stops the
instance from starting with a ``ConfigurationError`` naming the setting.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from podiumd_admin.adapters.db.readiness import database_is_reachable
from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.logging import configure_logging
from podiumd_admin.config import load_settings


def create_app_from_environment() -> FastAPI:
    """Load the settings from the environment and build the app with real adapters."""
    settings = load_settings()
    configure_logging()
    # Connections are opened lazily, so building the app needs no database.
    engine = create_async_engine(settings.database_app_url.get_secret_value(), pool_pre_ping=True)
    app = create_app(settings, readiness=partial(database_is_reachable, engine))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app.router.lifespan_context = lifespan
    return app
