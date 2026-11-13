"""The expiry sweep: abandoned Sessions are found without a request (task 7.4).

Spec: authentication, "Session lifetime and expiry", scenario "Abandoned
session": expired sessions are found by the server even if the user never
returns. Design D2: a background task ends sessions past their idle or
absolute limit, writes one ``session-expired``/``info`` entry per session and
purges the tokens. It also purges expired sign-in attempts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from podiumd_admin.application.sessions import SWEEP_BATCH_SIZE, Sessions
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from podiumd_admin.domain.sign_in import SIGN_IN_ATTEMPT_LIFETIME, SignInAttempt
from tests.application.conftest import AUTH_SETTINGS, NOW
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
    tokens,
)


@pytest.fixture
def sessions(
    identity_provider: FakeIdentityProvider,
    unit_of_work: FakeUnitOfWork,
    sink: FakeAuditSink,
    failures: UnauthenticatedFailureAggregator,
    clock: FakeClock,
) -> Sessions:
    return Sessions(
        settings=AUTH_SETTINGS,
        identity_provider=identity_provider,
        unit_of_work=unit_of_work,
        audit_sink=sink,
        failures=failures,
        clock=clock,
    )


def _session(subject: str = "f3b2c1d0", **overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": subject,
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER}),
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + AUTH_SETTINGS.timeouts.absolute_lifetime,
        "tokens": tokens(),
    }
    fields.update(overrides)
    return Session(**fields)


async def test_an_abandoned_session_gets_exactly_one_entry_and_loses_its_tokens(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock, sink: FakeAuditSink
) -> None:
    unit_of_work.sessions.sessions["abandoned"] = _session()
    clock.advance(AUTH_SETTINGS.timeouts.idle_timeout + timedelta(seconds=1))

    ended = await sessions.expire_abandoned()
    again = await sessions.expire_abandoned()

    assert (ended, again) == (1, 0)
    assert unit_of_work.sessions.sessions == {}
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "session-expired",
        Outcome.INFO,
        ReasonCode.IDLE,
    )
    assert entry.user_subject == "f3b2c1d0"
    assert entry.username == "j.jansen"
    assert entry.client_ip is None
    assert entry.correlation_id
    assert sink.stored == [entry]


async def test_a_session_past_its_lifetime_is_ended_with_max_lifetime(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    lifetime = AUTH_SETTINGS.timeouts.absolute_lifetime
    unit_of_work.sessions.sessions["long"] = _session(
        last_seen_at=NOW + lifetime - timedelta(minutes=1)
    )
    clock.advance(lifetime)

    await sessions.expire_abandoned()

    [entry] = unit_of_work.audit.entries
    assert entry.reason is ReasonCode.MAX_LIFETIME


async def test_active_sessions_are_left_alone(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    unit_of_work.sessions.sessions["active"] = _session(last_seen_at=NOW + timedelta(minutes=20))
    clock.advance(timedelta(minutes=31))

    assert await sessions.expire_abandoned() == 0
    assert "active" in unit_of_work.sessions.sessions
    assert unit_of_work.audit.entries == []


async def test_more_sessions_than_one_batch_are_all_ended(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    count = SWEEP_BATCH_SIZE * 2 + 3
    for number in range(count):
        unit_of_work.sessions.sessions[f"abandoned-{number}"] = _session(f"user-{number}")
    clock.advance(timedelta(hours=1))

    assert await sessions.expire_abandoned() == count
    assert len(unit_of_work.audit.entries) == count
    assert len({entry.correlation_id for entry in unit_of_work.audit.entries}) == 1


async def test_a_session_whose_entry_cannot_be_stored_is_kept_and_retried(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock, sink: FakeAuditSink
) -> None:
    unit_of_work.sessions.sessions["abandoned"] = _session()
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")
    clock.advance(timedelta(hours=1))

    assert await sessions.expire_abandoned() == 0
    assert "abandoned" in unit_of_work.sessions.sessions
    assert len(sink.write_failures) == 1

    unit_of_work.audit.error = None
    assert await sessions.expire_abandoned() == 1
    assert len(unit_of_work.audit.entries) == 1


async def test_expired_sign_in_attempts_are_purged(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    unit_of_work.sign_in_attempts.attempts["old"] = SignInAttempt(
        state="s" * 43, nonce="n" * 43, code_verifier="v" * 43, return_path="/", created_at=NOW
    )
    clock.advance(SIGN_IN_ATTEMPT_LIFETIME)

    await sessions.expire_abandoned()

    assert unit_of_work.sign_in_attempts.attempts == {}
