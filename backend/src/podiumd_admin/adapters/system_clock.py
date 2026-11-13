"""The Clock port on the system time."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Implements ``Clock``: the current system time in UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
