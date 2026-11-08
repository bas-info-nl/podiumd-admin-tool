"""The Clock port: the current time, replaceable in tests."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Tells the current time."""

    def now(self) -> datetime:
        """The current time as a timezone-aware datetime in UTC."""
        ...
