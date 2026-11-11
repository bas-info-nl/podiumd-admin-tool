"""The configured session timeouts.

Spec: authentication, "Session lifetime and expiry". Design D2: an idle
timeout of 30 minutes and an absolute lifetime of 8 hours by default, both
configurable, with the absolute lifetime at most 12 hours.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from podiumd_admin.domain.session_timeouts import (
    DEFAULT_ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT,
    MAX_ABSOLUTE_LIFETIME,
    InvalidSessionTimeoutsError,
    SessionTimeouts,
)


def test_defaults_are_30_minutes_idle_and_8_hours_absolute() -> None:
    timeouts = SessionTimeouts()

    assert timeouts.idle_timeout == timedelta(minutes=30) == DEFAULT_IDLE_TIMEOUT
    assert timeouts.absolute_lifetime == timedelta(hours=8) == DEFAULT_ABSOLUTE_LIFETIME


def test_the_absolute_lifetime_is_at_most_12_hours() -> None:
    assert timedelta(hours=12) == MAX_ABSOLUTE_LIFETIME
    assert SessionTimeouts(absolute_lifetime=timedelta(hours=12)).absolute_lifetime == (
        timedelta(hours=12)
    )

    with pytest.raises(InvalidSessionTimeoutsError, match="at most 12:00:00") as error:
        SessionTimeouts(absolute_lifetime=timedelta(hours=12, seconds=1))

    assert error.value.field == "absolute_lifetime"


@pytest.mark.parametrize("field", ["idle_timeout", "absolute_lifetime"])
@pytest.mark.parametrize("value", [timedelta(0), timedelta(minutes=-1)])
def test_timeouts_must_be_positive(field: str, value: timedelta) -> None:
    with pytest.raises(InvalidSessionTimeoutsError, match="must be positive") as error:
        SessionTimeouts(**{field: value})

    assert error.value.field == field


@pytest.mark.parametrize("field", ["idle_timeout", "absolute_lifetime"])
def test_timeouts_must_be_durations(field: str) -> None:
    with pytest.raises(InvalidSessionTimeoutsError, match="must be a duration") as error:
        SessionTimeouts(**{field: 30})  # type: ignore[arg-type]

    assert error.value.field == field


def test_the_idle_timeout_may_not_exceed_the_absolute_lifetime() -> None:
    assert SessionTimeouts(
        idle_timeout=timedelta(hours=1), absolute_lifetime=timedelta(hours=1)
    ).idle_timeout == timedelta(hours=1)

    with pytest.raises(InvalidSessionTimeoutsError, match="at most the absolute") as error:
        SessionTimeouts(idle_timeout=timedelta(hours=2), absolute_lifetime=timedelta(hours=1))

    assert error.value.field == "idle_timeout"


def test_the_error_carries_the_problem_without_the_field() -> None:
    """The configuration layer reports the problem under its own setting name."""
    with pytest.raises(InvalidSessionTimeoutsError) as error:
        SessionTimeouts(idle_timeout=timedelta(0))

    assert error.value.problem == "must be positive"
