"""Signing out (task 7.6).

Spec: authentication, "Sign-out"; audit-log, "No action without an Audit
Entry". Design D2 and D4: the ``sign-out``/``allowed`` entry is inserted
before the Session is removed, in one transaction; if it cannot be stored
the Session is kept. The SPA then navigates to Keycloak's
``end_session_endpoint`` with ``id_token_hint`` and a
``post_logout_redirect_uri`` built from ``publicHostname``.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from podiumd_admin.application.audit import AuditWriteFailedError
from podiumd_admin.application.sessions import ActiveSession, Sessions
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.application.conftest import AUTH_SETTINGS, CLIENT_IP, NOW, POST_LOGOUT_REDIRECT_URI
from tests.application.fakes import (
    END_SESSION_ENDPOINT,
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeTransactionAbortedError,
    FakeUnitOfWork,
    tokens,
)

SESSION_ID = "session-1"


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


@pytest.fixture
def active(unit_of_work: FakeUnitOfWork) -> ActiveSession:
    session = Session(
        user_subject="f3b2c1d0",
        username="j.jansen",
        keycloak_session_id="kc-sid-1",
        roles=frozenset({Role.VIEWER}),
        created_at=NOW,
        last_seen_at=NOW,
        expires_at=NOW + timedelta(hours=8),
        tokens=tokens(),
    )
    unit_of_work.sessions.sessions[SESSION_ID] = session
    return ActiveSession(session_id=SESSION_ID, session=session)


async def _sign_out(sessions: Sessions, active: ActiveSession) -> str:
    return await sessions.sign_out(active, client_ip=CLIENT_IP, correlation_id="c-sign-out")


async def test_sign_out_records_the_entry_then_ends_the_session(
    sessions: Sessions, active: ActiveSession, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    await _sign_out(sessions, active)

    assert unit_of_work.sessions.sessions == {}
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == ("sign-out", Outcome.ALLOWED, None)
    assert (entry.user_subject, entry.username) == ("f3b2c1d0", "j.jansen")
    assert (entry.client_ip, entry.correlation_id) == (CLIENT_IP, "c-sign-out")
    assert sink.stored == [entry]


async def test_sign_out_returns_the_end_session_url(
    sessions: Sessions, active: ActiveSession
) -> None:
    url = await _sign_out(sessions, active)

    assert url.startswith(END_SESSION_ENDPOINT)
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    assert query == {"id_token_hint": "id-1", "post_logout_redirect_uri": POST_LOGOUT_REDIRECT_URI}


async def test_the_session_is_kept_when_the_entry_cannot_be_stored(
    sessions: Sessions, active: ActiveSession, unit_of_work: FakeUnitOfWork
) -> None:
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")

    with pytest.raises(AuditWriteFailedError):
        await _sign_out(sessions, active)

    assert SESSION_ID in unit_of_work.sessions.sessions


async def test_the_session_is_kept_when_the_transaction_is_aborted(
    sessions: Sessions, active: ActiveSession, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    """Issue #30."""
    unit_of_work.abort_next_audited_commit = True

    with pytest.raises(FakeTransactionAbortedError):
        await _sign_out(sessions, active)

    assert SESSION_ID in unit_of_work.sessions.sessions
    assert unit_of_work.audit.entries == []
    assert sink.stored == []
