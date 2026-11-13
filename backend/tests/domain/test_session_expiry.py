"""When a Session ends by itself, and when its access token needs a refresh (task 7.3).

Spec: authentication, "Session lifetime and expiry": a session ends when the
user is idle longer than the idle timeout or the absolute lifetime is
reached; once the access token has expired, it is refreshed before the
request is authorised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from podiumd_admin.domain.audit import ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import (
    Session,
    SessionTokens,
    access_token_expired,
    expiry_reason,
    highest_role,
)
from podiumd_admin.domain.session_timeouts import SessionTimeouts

CREATED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
TIMEOUTS = SessionTimeouts(idle_timeout=timedelta(minutes=30), absolute_lifetime=timedelta(hours=8))


def _session(**overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": "f3b2c1d0",
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER}),
        "created_at": CREATED_AT,
        "last_seen_at": CREATED_AT,
        "expires_at": CREATED_AT + TIMEOUTS.absolute_lifetime,
        "tokens": None,
    }
    fields.update(overrides)
    return Session(**fields)


@pytest.mark.parametrize(
    ("idle_for", "expected"),
    [
        (timedelta(minutes=29, seconds=59), None),
        (timedelta(minutes=30), ReasonCode.IDLE),
        (timedelta(hours=2), ReasonCode.IDLE),
    ],
)
def test_an_idle_session_expires(idle_for: timedelta, expected: ReasonCode | None) -> None:
    assert expiry_reason(_session(), CREATED_AT + idle_for, TIMEOUTS) is expected


def test_an_active_session_expires_at_its_absolute_lifetime() -> None:
    end = CREATED_AT + TIMEOUTS.absolute_lifetime
    session = _session(last_seen_at=end - timedelta(minutes=1))

    assert expiry_reason(session, end - timedelta(seconds=1), TIMEOUTS) is None
    assert expiry_reason(session, end, TIMEOUTS) is ReasonCode.MAX_LIFETIME


def test_the_absolute_lifetime_wins_when_both_have_passed() -> None:
    assert (
        expiry_reason(_session(), CREATED_AT + timedelta(hours=9), TIMEOUTS)
        is ReasonCode.MAX_LIFETIME
    )


def test_an_access_token_expires_slightly_early() -> None:
    """A token that would expire on its way to Keycloak counts as expired."""
    tokens = SessionTokens(
        access_token="access-1",  # noqa: S106 - a test value, not a secret
        refresh_token=None,
        id_token=None,
        access_token_expires_at=CREATED_AT + timedelta(minutes=5),
    )

    assert not access_token_expired(tokens, CREATED_AT + timedelta(minutes=4))
    assert access_token_expired(tokens, CREATED_AT + timedelta(minutes=4, seconds=50))
    assert access_token_expired(tokens, CREATED_AT + timedelta(minutes=6))


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (frozenset(), None),
        (frozenset({Role.VIEWER}), Role.VIEWER),
        (frozenset({Role.OPERATOR}), Role.OPERATOR),
        (frozenset({Role.VIEWER, Role.OPERATOR}), Role.OPERATOR),
    ],
)
def test_the_highest_role_counts(roles: frozenset[Role], expected: Role | None) -> None:
    assert highest_role(roles) is expected
