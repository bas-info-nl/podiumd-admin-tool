"""Completing a sign-in: the OIDC callback (task 7.2).

Spec: authentication, "Sign-in through the Environment's Keycloak" and
"Sessions are held by the server"; access-control, "Users without a role are
refused"; audit-log, "Recording unauthenticated failures" and "No action
without an Audit Entry". Design D2 and D4.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from podiumd_admin.application.audit import AuditWriteFailedError
from podiumd_admin.application.sign_in import NoAccess, SignedIn, SignIn, SignInFailed
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session_timeouts import DEFAULT_ABSOLUTE_LIFETIME
from podiumd_admin.domain.sign_in import SIGN_IN_ATTEMPT_LIFETIME
from tests.application.conftest import AUTH_SETTINGS, CLIENT_IP, ENVIRONMENT, NOW, REDIRECT_URI
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeTransactionAbortedError,
    FakeUnitOfWork,
    identity,
)


@pytest.fixture
def sign_in(
    identity_provider: FakeIdentityProvider,
    unit_of_work: FakeUnitOfWork,
    sink: FakeAuditSink,
    failures: UnauthenticatedFailureAggregator,
    clock: FakeClock,
) -> SignIn:
    return SignIn(
        settings=AUTH_SETTINGS,
        identity_provider=identity_provider,
        unit_of_work=unit_of_work,
        audit_sink=sink,
        failures=failures,
        clock=clock,
    )


async def _complete(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    *,
    state: str | None = None,
    code: str | None = "code-1",
    error: str | None = None,
    attempt_id: str | None = None,
    client_ip: str | None = CLIENT_IP,
) -> SignedIn | NoAccess | SignInFailed:
    """Start a sign-in, then complete it with the attempt's own state unless one is given."""
    started = await sign_in.start("/audit-log")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    return await sign_in.complete(
        attempt_id=started.attempt_id if attempt_id is None else attempt_id,
        state=attempt.state if state is None else state,
        code=code,
        error=error,
        client_ip=client_ip,
        correlation_id="c-callback",
    )


def _failure_reasons(
    failures: UnauthenticatedFailureAggregator, sink: FakeAuditSink
) -> list[tuple[str | None, ReasonCode, int]]:
    failures.flush_all()
    return [(line.client_ip, line.reason, line.count) for line in sink.summaries]


# --- A user with a role --------------------------------------------------------------


async def test_a_user_with_a_role_gets_a_new_session(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, identity_provider: FakeIdentityProvider
) -> None:
    result = await _complete(sign_in, unit_of_work)

    assert isinstance(result, SignedIn)
    assert result.return_path == "/audit-log"
    session = unit_of_work.sessions.sessions[result.session_id]
    assert session.user_subject == identity_provider.identity.subject
    assert session.username == "j.jansen"
    assert session.keycloak_session_id == "kc-sid-1"
    assert session.roles == frozenset({Role.VIEWER})
    assert session.created_at == session.last_seen_at == NOW
    assert session.expires_at == NOW + DEFAULT_ABSOLUTE_LIFETIME
    assert session.tokens == identity_provider.identity.tokens


async def test_the_session_id_is_new_and_unrelated_to_the_attempt(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork
) -> None:
    started = await sign_in.start("/")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]

    result = await sign_in.complete(
        attempt_id=started.attempt_id,
        state=attempt.state,
        code="code-1",
        error=None,
        client_ip=CLIENT_IP,
        correlation_id="c-1",
    )

    assert isinstance(result, SignedIn)
    assert result.session_id not in {started.attempt_id, attempt.state, attempt.nonce}
    assert len(result.session_id) >= 43


async def test_exactly_one_allowed_entry_is_recorded(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    await _complete(sign_in, unit_of_work)

    [entry] = unit_of_work.audit.entries
    assert entry.action == "sign-in"
    assert entry.outcome is Outcome.ALLOWED
    assert entry.reason is None
    assert entry.user_subject == "f3b2c1d0-0000-4000-8000-000000000001"
    assert entry.username == "j.jansen"
    assert entry.environment == ENVIRONMENT
    assert entry.client_ip == CLIENT_IP
    assert entry.correlation_id == "c-callback"
    assert entry.occurred_at == NOW
    assert sink.stored == [entry]


async def test_the_code_is_exchanged_with_the_attempts_verifier_and_nonce(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, identity_provider: FakeIdentityProvider
) -> None:
    started = await sign_in.start("/")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]

    await sign_in.complete(
        attempt_id=started.attempt_id,
        state=attempt.state,
        code="code-1",
        error=None,
        client_ip=CLIENT_IP,
        correlation_id="c-1",
    )

    assert identity_provider.exchanges == [
        {
            "code": "code-1",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": attempt.code_verifier,
            "nonce": attempt.nonce,
        }
    ]


async def test_an_operator_role_wins_over_viewer(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, identity_provider: FakeIdentityProvider
) -> None:
    identity_provider.identity = identity(["viewer", "operator"])

    result = await _complete(sign_in, unit_of_work)

    assert isinstance(result, SignedIn)
    assert unit_of_work.sessions.sessions[result.session_id].roles == frozenset({Role.OPERATOR})


async def test_an_attempt_can_be_used_once(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    started = await sign_in.start("/")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    arguments = {
        "attempt_id": started.attempt_id,
        "state": attempt.state,
        "code": "code-1",
        "error": None,
        "client_ip": CLIENT_IP,
        "correlation_id": "c-1",
    }

    first = await sign_in.complete(**arguments)  # type: ignore[arg-type]
    second = await sign_in.complete(**arguments)  # type: ignore[arg-type]

    assert isinstance(first, SignedIn)
    assert second == SignInFailed(ReasonCode.INVALID_STATE)
    assert len(unit_of_work.sessions.sessions) == 1


# --- A user without a role ---------------------------------------------------------------


@pytest.mark.parametrize("roles", [None, [], ["admin"]])
async def test_a_user_without_a_role_gets_no_session_and_one_denied_entry(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    roles: list[str] | None,
) -> None:
    identity_provider.identity = identity(roles)

    result = await _complete(sign_in, unit_of_work)

    assert result == NoAccess()
    assert unit_of_work.sessions.sessions == {}
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "sign-in",
        Outcome.DENIED,
        ReasonCode.NO_ROLE,
    )
    assert entry.user_subject == identity_provider.identity.subject
    assert entry.client_ip == CLIENT_IP


async def test_a_user_without_a_role_is_refused_even_if_the_entry_cannot_be_stored(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    sink: FakeAuditSink,
) -> None:
    identity_provider.identity = identity([])
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")

    result = await _complete(sign_in, unit_of_work)

    assert result == NoAccess()
    assert unit_of_work.sessions.sessions == {}
    [(entry, _error)] = sink.write_failures
    assert entry.reason is ReasonCode.NO_ROLE


# --- Failed callbacks -------------------------------------------------------------------


async def test_a_state_that_does_not_match_creates_no_session(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    result = await _complete(sign_in, unit_of_work, state="forged-state")

    assert result == SignInFailed(ReasonCode.INVALID_STATE)
    assert unit_of_work.sessions.sessions == {}
    assert unit_of_work.audit.entries == []
    assert identity_provider.exchanges == []
    assert unit_of_work.sign_in_attempts.attempts == {}
    assert _failure_reasons(failures, sink) == [(CLIENT_IP, ReasonCode.INVALID_STATE, 1)]


@pytest.mark.parametrize("attempt_id", ["unknown-attempt", ""])
async def test_an_unknown_attempt_creates_no_session(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
    attempt_id: str,
) -> None:
    result = await _complete(sign_in, unit_of_work, attempt_id=attempt_id)

    assert result == SignInFailed(ReasonCode.INVALID_STATE)
    assert unit_of_work.sessions.sessions == {}
    assert _failure_reasons(failures, sink) == [(CLIENT_IP, ReasonCode.INVALID_STATE, 1)]


async def test_an_expired_attempt_creates_no_session(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    clock: FakeClock,
) -> None:
    started = await sign_in.start("/")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    clock.advance(SIGN_IN_ATTEMPT_LIFETIME)

    result = await sign_in.complete(
        attempt_id=started.attempt_id,
        state=attempt.state,
        code="code-1",
        error=None,
        client_ip=CLIENT_IP,
        correlation_id="c-1",
    )

    assert result == SignInFailed(ReasonCode.INVALID_STATE)
    assert unit_of_work.sessions.sessions == {}


async def test_an_error_from_keycloak_creates_no_session(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    result = await _complete(sign_in, unit_of_work, error="access_denied", code=None)

    assert result == SignInFailed(ReasonCode.CALLBACK_ERROR)
    assert identity_provider.exchanges == []
    assert unit_of_work.sessions.sessions == {}
    assert _failure_reasons(failures, sink) == [(CLIENT_IP, ReasonCode.CALLBACK_ERROR, 1)]


async def test_a_callback_without_a_code_creates_no_session(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork
) -> None:
    result = await _complete(sign_in, unit_of_work, code=None)

    assert result == SignInFailed(ReasonCode.CALLBACK_ERROR)
    assert unit_of_work.sessions.sessions == {}


async def test_a_failed_token_exchange_creates_no_session(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    identity_provider: FakeIdentityProvider,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    identity_provider.exchange_fails = True

    result = await _complete(sign_in, unit_of_work)

    assert result == SignInFailed(ReasonCode.TOKEN_EXCHANGE_FAILED)
    assert unit_of_work.sessions.sessions == {}
    assert unit_of_work.audit.entries == []
    assert _failure_reasons(failures, sink) == [(CLIENT_IP, ReasonCode.TOKEN_EXCHANGE_FAILED, 1)]


async def test_a_failure_without_a_client_ip_is_not_counted(
    sign_in: SignIn,
    unit_of_work: FakeUnitOfWork,
    failures: UnauthenticatedFailureAggregator,
    sink: FakeAuditSink,
) -> None:
    result = await _complete(sign_in, unit_of_work, state="forged-state", client_ip=None)

    assert result == SignInFailed(ReasonCode.INVALID_STATE)
    assert _failure_reasons(failures, sink) == []


# --- The Audit Log is unavailable ----------------------------------------------------------


async def test_no_session_when_the_entry_cannot_be_stored(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")

    with pytest.raises(AuditWriteFailedError):
        await _complete(sign_in, unit_of_work)

    assert unit_of_work.sessions.sessions == {}
    assert sink.stored == []
    [(entry, _error)] = sink.write_failures
    assert (entry.action, entry.outcome) == ("sign-in", Outcome.ALLOWED)


async def test_no_session_when_the_transaction_is_aborted(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    """Issue #30: the commit rolls back although no statement raised."""
    started = await sign_in.start("/")
    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    unit_of_work.abort_next_audited_commit = True

    with pytest.raises(FakeTransactionAbortedError):
        await sign_in.complete(
            attempt_id=started.attempt_id,
            state=attempt.state,
            code="code-1",
            error=None,
            client_ip=CLIENT_IP,
            correlation_id="c-1",
        )

    assert unit_of_work.sessions.sessions == {}
    assert unit_of_work.audit.entries == []
    assert sink.stored == []


def test_the_attempt_lifetime_is_short() -> None:
    assert timedelta(minutes=1) <= SIGN_IN_ATTEMPT_LIFETIME <= timedelta(minutes=15)
