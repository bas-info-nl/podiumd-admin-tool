"""Periodic background jobs of the single replica (design D2, ADR 0010).

The expiry sweep and the flush of the unauthenticated-failure aggregator run
every ``SWEEP_INTERVAL`` in the one backend replica. Each job runs at once
when the app starts and then after every interval. A run that fails is logged
and the next run happens as usual; leaving ``periodic_jobs`` cancels them.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Final

import structlog

SWEEP_INTERVAL: Final = timedelta(minutes=1)

type Job = Callable[[], Awaitable[object]]

_logger = structlog.get_logger(__name__)


async def _run_every(name: str, job: Job, interval: timedelta) -> None:
    while True:
        try:
            await job()
        except Exception:
            _logger.exception("background_job_failed", job=name)
        await asyncio.sleep(interval.total_seconds())


@contextlib.asynccontextmanager
async def periodic_jobs(
    jobs: Mapping[str, Job], *, interval: timedelta = SWEEP_INTERVAL
) -> AsyncIterator[None]:
    """Run every job in ``jobs`` every ``interval`` until the block ends."""
    tasks = [
        asyncio.create_task(_run_every(name, job, interval), name=name)
        for name, job in jobs.items()
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
