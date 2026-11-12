"""How long a session may stay idle, and how long it may last at most.

Spec: authentication, "Session lifetime and expiry". Design D2: the idle
timeout defaults to 30 minutes and the absolute lifetime to 8 hours. Both are
configurable, but the absolute lifetime is at most 12 hours. A configured
value outside these limits is rejected when the instance starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal

DEFAULT_IDLE_TIMEOUT: Final = timedelta(minutes=30)
DEFAULT_ABSOLUTE_LIFETIME: Final = timedelta(hours=8)
MAX_ABSOLUTE_LIFETIME: Final = timedelta(hours=12)

type TimeoutField = Literal["idle_timeout", "absolute_lifetime"]


class InvalidSessionTimeoutsError(ValueError):
    """A configured session timeout is invalid.

    ``field`` names the offending timeout and ``problem`` says what is wrong
    with it, so the configuration layer can report the problem under the
    setting it came from.
    """

    def __init__(self, field: TimeoutField, problem: str) -> None:
        super().__init__(f"invalid session timeouts: {field} {problem}")
        self.field: TimeoutField = field
        self.problem = problem


@dataclass(frozen=True, slots=True)
class SessionTimeouts:
    """The idle timeout and the absolute lifetime of every session."""

    idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT
    absolute_lifetime: timedelta = DEFAULT_ABSOLUTE_LIFETIME

    def __post_init__(self) -> None:
        for field in ("idle_timeout", "absolute_lifetime"):
            value = getattr(self, field)
            if not isinstance(value, timedelta):
                raise InvalidSessionTimeoutsError(field, "must be a duration")
            if value <= timedelta(0):
                raise InvalidSessionTimeoutsError(field, "must be positive")
        if self.absolute_lifetime > MAX_ABSOLUTE_LIFETIME:
            raise InvalidSessionTimeoutsError(
                "absolute_lifetime", f"must be at most {MAX_ABSOLUTE_LIFETIME}"
            )
        if self.idle_timeout > self.absolute_lifetime:
            raise InvalidSessionTimeoutsError(
                "idle_timeout", "must be at most the absolute lifetime"
            )
