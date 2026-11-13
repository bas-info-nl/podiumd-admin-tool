"""SystemClock: the Clock port on the system time."""

from __future__ import annotations

from datetime import UTC, datetime

from podiumd_admin.adapters.system_clock import SystemClock
from podiumd_admin.ports.clock import Clock


def test_the_system_clock_tells_the_current_utc_time() -> None:
    clock: Clock = SystemClock()

    before = datetime.now(UTC)
    now = clock.now()

    assert now.tzinfo is UTC
    assert before <= now <= datetime.now(UTC)
