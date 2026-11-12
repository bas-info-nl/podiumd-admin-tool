"""Whether the database is reachable, for the readiness endpoint.

Spec: installation, "Health endpoints". The check runs ``SELECT 1`` as the
app role and answers ``False`` on any failure or when the database does not
answer in time; it never raises and never reports why, so ``/readyz`` cannot
reveal configuration.
"""

from __future__ import annotations

import asyncio
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

DEFAULT_TIMEOUT_SECONDS: Final = 2.0


async def database_is_reachable(
    engine: AsyncEngine,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,  # noqa: ASYNC109 - the probe owns its deadline
) -> bool:
    """Whether ``SELECT 1`` succeeds within ``timeout`` seconds."""
    try:
        async with asyncio.timeout(timeout), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
