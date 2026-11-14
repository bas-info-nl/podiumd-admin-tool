"""Resuming a Session on every request (task 7.3).

Spec: authentication, "Session lifetime and expiry"; access-control, "Roles"
(roles are re-evaluated at every token refresh). Design D2:

- a session past its idle timeout or absolute lifetime ends, with exactly one
  ``session-expired``/``info`` Audit Entry (``idle`` or ``max-lifetime``);
- an expired access token is refreshed before the request is authorised,
  and the roles are read again from the new token;
- a refused refresh ends the session with ``refresh-refused``;
- an unknown or ended session gives no session (the HTTP layer answers 401)
  and counts as an unauthenticated failure on stdout.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from podiumd_admin.application.sessions import ActiveSession, Sessions
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError
from tests.application.conftest import AUTH_SETTINGS, CLIENT_IP, ENVIRONMENT, NOW
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
    identity,
    tokens,
)

SESSION_ID = "session-id-from-the-cookie"
SUBJECT = "f3b2c1d0-0000-4000-8000-000000000001"


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


def _session(**overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": SUBJECT,
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER}),
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + AUTH_SETTINGS.timeouts.absolute_lifetime,
        "tokens": tokens(expires_at=NOW + timedelta(minutes=5)),
    }
    fields.update(overrides)
    return Session(**fields)


async def _resume(sessions: Sessions, session_id: str | None = SESSION_ID) -> ActiveSession | None:
    return await sessions.resume(session_id, client_ip=CLIENT_IP, correlation_id="c-request")


def _summaries(
    failures: UnauthenticatedFailureAggregator, sink: FakeAuditSink
) -> list[tuple[str | None, ReasonCode, int]]:
    failures.flush_all()
    return [(line.client_ip, line.reason, line.count) for line in sink.summaries]


# --- An active session -------------------------------------------------------------------


async def test_an_active_session_is_resumed_and_touched(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    clock.advance(timedelta(minutes=2))

    active = await _resume(sessions)

    assert active is not None
    assert active.session_id == SESSION_ID
    assert active.user.subject == SUBJECT
    assert active.user.role is Role.VIEWER
    assert active.session.username == "j.jansen"
    assert unit_of_work.sessions.sessions[SESSION_ID].last_seen_at == NOW + timedelta(minutes=2)
    assert unit_of_work.audit.entries == []


async def test_a_fresh_access_token_is_not_refreshed(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, identity_provider: FakeIdentityProvider
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()

    await _resume(sessions)

    assert identity_provider.refreshes == []


# --- Unknown sessions --------------------------------------------------------------------


@pytest.mark.parametrize("session_id", [None, "", "never-issued"])
async def test_an_unknown_session_gives_none_and_counts_on_stdout(
    sessions: Sessions,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
    unit_of_work: FakeUnitOfWork,
    session_id: str | None,
) -> None:
    assert await _resume(sessions, session_id) is None
    assert unit_of_work.audit.entries == []
    assert _summaries(failures, sink) == [(CLIENT_IP, ReasonCode.NO_SESSION, 1)]


async def test_an_unknown_session_without_a_client_ip_is_not_counted(
    sessions: Sessions, failures: UnauthenticatedFailureAggregator, sink: FakeAuditSink
) -> None:
    assert await sessions.resume("never-issued", client_ip=None, correlation_id="c-1") is None
    assert _summaries(failures, sink) == []


# --- Idle and absolute expiry -------------------------------------------------------------


@pytest.mark.parametrize(
    ("advance", "last_seen", "reason"),
    [
        (timedelta(minutes=30), timedelta(0), ReasonCode.IDLE),
        (timedelta(hours=8), timedelta(hours=7, minutes=59), ReasonCode.MAX_LIFETIME),
    ],
)
async def test_an_expired_session_ends_with_one_entry(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    clock: FakeClock,
    sink: FakeAuditSink,
    advance: timedelta,
    last_seen: timedelta,
    reason: ReasonCode,
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session(last_seen_at=NOW + last_seen)
    clock.advance(advance)

    first = await _resume(sessions)
    second = await _resume(sessions)

    assert first is None
    assert second is None
    assert unit_of_work.sessions.sessions == {}
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == ("session-expired", Outcome.INFO, reason)
    assert entry.user_subject == SUBJECT
    assert entry.username == "j.jansen"
    assert entry.environment == ENVIRONMENT
    assert entry.client_ip == CLIENT_IP
    assert entry.correlation_id == "c-request"
    assert sink.stored == [entry]


async def test_an_expired_session_whose_entry_cannot_be_stored_is_kept_for_the_sweep(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock, sink: FakeAuditSink
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")
    clock.advance(timedelta(minutes=31))

    assert await _resume(sessions) is None

    assert SESSION_ID in unit_of_work.sessions.sessions
    [(entry, _error)] = sink.write_failures
    assert entry.reason is ReasonCode.IDLE


async def test_an_idle_session_touched_by_an_overlapping_request_is_not_ended(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, clock: FakeClock
) -> None:
    """Another request read the Session in time and saves its touch after this read."""
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    clock.advance(AUTH_SETTINGS.timeouts.idle_timeout)
    original_get = unit_of_work.sessions.get

    async def get_then_touch(session_id: str) -> Session | None:
        stale = await original_get(session_id)
        if stale is not None:
            unit_of_work.sessions.sessions[session_id] = replace(stale, last_seen_at=clock.now())
        return stale

    unit_of_work.sessions.get = get_then_touch  # type: ignore[method-assign]

    assert await _resume(sessions) is None

    assert unit_of_work.sessions.sessions[SESSION_ID].last_seen_at == clock.now()
    assert unit_of_work.audit.entries == []


# --- Refresh -------------------------------------------------------------------------------


async def test_an_expired_access_token_is_refreshed_before_authorisation(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    clock: FakeClock,
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    clock.advance(timedelta(minutes=6))
    new_tokens = tokens(expires_at=clock.now() + timedelta(minutes=5), suffix="2")
    identity_provider.refreshed = identity(["operator"], session_tokens=new_tokens)

    active = await _resume(sessions)

    assert identity_provider.refreshes == ["refresh-1"]
    assert active is not None
    assert active.user.role is Role.OPERATOR
    stored = unit_of_work.sessions.sessions[SESSION_ID]
    assert stored.roles == frozenset({Role.OPERATOR})
    assert stored.tokens == new_tokens
    assert stored.last_seen_at == clock.now()


async def test_a_role_removed_in_keycloak_is_gone_after_the_refresh(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    clock: FakeClock,
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    clock.advance(timedelta(minutes=6))
    identity_provider.refreshed = identity(
        [], session_tokens=tokens(clock.now() + timedelta(minutes=5))
    )

    active = await _resume(sessions)

    assert active is not None
    assert active.user.role is None
    assert unit_of_work.sessions.sessions[SESSION_ID].roles == frozenset()


async def test_a_refresh_without_new_id_or_refresh_token_keeps_the_old_ones(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    clock: FakeClock,
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    clock.advance(timedelta(minutes=6))
    partial = tokens(clock.now() + timedelta(minutes=5), suffix="2")
    partial = type(partial)(
        access_token=partial.access_token,
        refresh_token=None,
        id_token=None,
        access_token_expires_at=partial.access_token_expires_at,
    )
    identity_provider.refreshed = identity(["viewer"], session_tokens=partial)

    await _resume(sessions)

    stored_tokens = unit_of_work.sessions.sessions[SESSION_ID].tokens
    assert stored_tokens is not None
    assert stored_tokens.access_token == "access-2"  # noqa: S105
    assert stored_tokens.refresh_token == "refresh-1"  # noqa: S105
    assert stored_tokens.id_token == "id-1"  # noqa: S105


@pytest.mark.parametrize("cause", ["refused", "no-refresh-token", "other-subject"])
async def test_a_refused_refresh_ends_the_session(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    clock: FakeClock,
    cause: str,
) -> None:
    session = _session()
    if cause == "no-refresh-token":
        assert session.tokens is not None
        session = _session(
            tokens=type(session.tokens)(
                access_token="access-1",  # noqa: S106
                refresh_token=None,
                id_token=None,
                access_token_expires_at=session.tokens.access_token_expires_at,
            )
        )
    unit_of_work.sessions.sessions[SESSION_ID] = session
    identity_provider.refresh_refused = cause == "refused"
    if cause == "other-subject":
        identity_provider.refreshed = identity(["viewer"], subject="someone-else")
    clock.advance(timedelta(minutes=6))

    assert await _resume(sessions) is None

    assert unit_of_work.sessions.sessions == {}
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "session-expired",
        Outcome.INFO,
        ReasonCode.REFRESH_REFUSED,
    )


async def test_an_unreachable_keycloak_keeps_the_session(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    clock: FakeClock,
) -> None:
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    identity_provider.unavailable = True
    clock.advance(timedelta(minutes=6))

    with pytest.raises(IdentityProviderUnavailableError):
        await _resume(sessions)

    assert SESSION_ID in unit_of_work.sessions.sessions
    assert unit_of_work.audit.entries == []


async def test_a_session_ended_meanwhile_is_not_resumed(
    sessions: Sessions, unit_of_work: FakeUnitOfWork
) -> None:
    """Sign-out in another tab between reading and touching the session."""
    unit_of_work.sessions.sessions[SESSION_ID] = _session()
    original_save = unit_of_work.sessions.save

    async def save_after_removal(session_id: str, session: Session) -> bool:
        unit_of_work.sessions.sessions.pop(session_id, None)
        return await original_save(session_id, session)

    unit_of_work.sessions.save = save_after_removal  # type: ignore[method-assign]

    assert await _resume(sessions) is None
