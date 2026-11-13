"""Back-channel logout: Keycloak ends a user's sessions (task 7.5).

Spec: authentication, "Session lifetime and expiry": a session ends when
Keycloak notifies the tool that the user's Keycloak session ended. Design D2:
the logout token is validated against Keycloak's JWKS and the sessions with
a matching ``sid`` end, each with one ``session-expired``/``info`` entry with
reason ``backchannel-logout``. An invalid token ends nothing and counts as an
unauthenticated failure on stdout.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from podiumd_admin.application.sessions import Sessions
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from podiumd_admin.ports.identity_provider import InvalidLogoutTokenError
from tests.application.conftest import AUTH_SETTINGS, CLIENT_IP, NOW
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
    tokens,
)

VALID = "valid-logout-token"


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


def _session(sid: str | None, subject: str = "f3b2c1d0", **overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": subject,
        "username": "j.jansen",
        "keycloak_session_id": sid,
        "roles": frozenset({Role.VIEWER}),
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(hours=8),
        "tokens": tokens(),
    }
    fields.update(overrides)
    return Session(**fields)


async def test_the_sessions_with_the_sid_end_with_one_entry_each(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    sink: FakeAuditSink,
) -> None:
    identity_provider.logout_sid = "kc-sid-1"
    unit_of_work.sessions.sessions.update(
        {
            "tab-1": _session("kc-sid-1"),
            "tab-2": _session("kc-sid-1"),
            "other": _session("kc-sid-2", subject="someone-else"),
        }
    )

    ended = await sessions.end_by_logout_token(VALID, client_ip=CLIENT_IP, correlation_id="c-bcl")

    assert ended == 2
    assert set(unit_of_work.sessions.sessions) == {"other"}
    assert len(unit_of_work.audit.entries) == 2
    for entry in unit_of_work.audit.entries:
        assert (entry.action, entry.outcome, entry.reason) == (
            "session-expired",
            Outcome.INFO,
            ReasonCode.BACKCHANNEL_LOGOUT,
        )
        assert entry.user_subject == "f3b2c1d0"
        assert entry.correlation_id == "c-bcl"
        # The request comes from Keycloak, not from the user's browser.
        assert entry.client_ip is None
    assert sink.stored == unit_of_work.audit.entries


async def test_a_sid_without_sessions_ends_nothing(
    sessions: Sessions, unit_of_work: FakeUnitOfWork, identity_provider: FakeIdentityProvider
) -> None:
    identity_provider.logout_sid = "kc-sid-unknown"
    unit_of_work.sessions.sessions["tab-1"] = _session("kc-sid-1")

    assert await sessions.end_by_logout_token(VALID, client_ip=CLIENT_IP, correlation_id="c") == 0
    assert unit_of_work.audit.entries == []


async def test_an_invalid_token_ends_nothing_and_counts_on_stdout(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    identity_provider.logout_sid = "kc-sid-1"
    unit_of_work.sessions.sessions["tab-1"] = _session("kc-sid-1")

    with pytest.raises(InvalidLogoutTokenError):
        await sessions.end_by_logout_token("forged", client_ip=CLIENT_IP, correlation_id="c")

    assert "tab-1" in unit_of_work.sessions.sessions
    assert unit_of_work.audit.entries == []
    failures.flush_all()
    assert [(line.client_ip, line.reason) for line in sink.summaries] == [
        (CLIENT_IP, ReasonCode.INVALID_LOGOUT_TOKEN)
    ]


async def test_an_entry_that_cannot_be_stored_keeps_that_session(
    sessions: Sessions,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    sink: FakeAuditSink,
) -> None:
    """Keycloak sees a failure and the session ends at its next expiry instead."""
    identity_provider.logout_sid = "kc-sid-1"
    unit_of_work.sessions.sessions["tab-1"] = _session("kc-sid-1")
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")

    with pytest.raises(RuntimeError):
        await sessions.end_by_logout_token(VALID, client_ip=CLIENT_IP, correlation_id="c")

    assert "tab-1" in unit_of_work.sessions.sessions
    assert len(sink.write_failures) == 1
