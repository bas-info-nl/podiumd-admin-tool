"""Periodic background jobs, such as the expiry sweep (task 7.4).

Design D2: the expiry sweep runs every minute in the single replica
(ADR 0010). A failing run is logged and does not stop the next one; leaving
the context stops the jobs.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from podiumd_admin.adapters.background import SWEEP_INTERVAL, periodic_jobs

TICK = timedelta(milliseconds=10)


class CountingJob:
    """A job that counts its runs and signals once it has run ``target`` times."""

    def __init__(self, target: int, error: Exception | None = None) -> None:
        self.calls = 0
        self.target = target
        self.error = error
        self.reached = asyncio.Event()

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls >= self.target:
            self.reached.set()
        if self.error is not None:
            raise self.error

    async def wait(self) -> None:
        async with asyncio.timeout(5):
            await self.reached.wait()


def test_the_sweep_runs_every_minute() -> None:
    assert timedelta(minutes=1) == SWEEP_INTERVAL


async def test_a_job_runs_at_once_and_then_every_interval() -> None:
    job = CountingJob(target=3)

    async with periodic_jobs({"count": job}, interval=TICK):
        await job.wait()

    assert job.calls >= 3


async def test_a_failing_run_does_not_stop_the_next() -> None:
    job = CountingJob(target=2, error=RuntimeError("database unreachable"))

    async with periodic_jobs({"failing": job}, interval=TICK):
        await job.wait()

    assert job.calls >= 2


async def test_leaving_the_context_stops_the_jobs() -> None:
    job = CountingJob(target=1)

    async with periodic_jobs({"count": job}, interval=TICK):
        await job.wait()
    stopped_at = job.calls
    await asyncio.sleep(TICK.total_seconds() * 5)

    assert job.calls == stopped_at
