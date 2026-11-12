"""The database readiness check behind ``/readyz`` (task 6.5).

Spec: installation, "Health endpoints", scenario "Database unreachable".
"""

from __future__ import annotations

import socket

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from podiumd_admin.adapters.db.readiness import database_is_reachable

pytestmark = pytest.mark.integration


async def test_a_reachable_database_is_ready(app_engine: AsyncEngine) -> None:
    assert await database_is_reachable(app_engine) is True


def _closed_port() -> int:
    """A local port nothing listens on: bound and released again."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


async def test_an_unreachable_database_is_not_ready() -> None:
    engine = create_async_engine(
        f"postgresql+psycopg://app:pw@127.0.0.1:{_closed_port()}/podiumd_admin",
        poolclass=NullPool,
    )
    try:
        assert await database_is_reachable(engine) is False
    finally:
        await engine.dispose()


async def test_a_database_that_does_not_answer_in_time_is_not_ready() -> None:
    """A listening socket that never answers: the check gives up after its timeout."""
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        port = silent.getsockname()[1]
        engine = create_async_engine(
            f"postgresql+psycopg://app:pw@127.0.0.1:{port}/podiumd_admin", poolclass=NullPool
        )
        try:
            assert await database_is_reachable(engine, timeout=0.2) is False
        finally:
            await engine.dispose()
