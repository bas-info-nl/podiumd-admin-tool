"""Authorising an action of a signed-in user, and recording a refusal (task 7.6).

Spec: access-control, "Every request is authorised on the server" and
"Actions are protected against cross-site requests"; audit-log, "No action
without an Audit Entry" (a denial is refused even if its entry cannot be
stored). Sign-out is the first action that needs this; task group 8 builds
the generic ``require(permission)`` dependency and CSRF guard on it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from podiumd_admin.application.authorisation import AccessDeniedError, Authoriser
from podiumd_admin.application.sessions import ActiveSession
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.authorisation import Permission
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.application.conftest import AUTH_SETTINGS, CLIENT_IP, ENVIRONMENT, NOW
from tests.application.fakes import FakeAuditSink, FakeClock, FakeUnitOfWork, tokens

TARGET = "POST /api/v1/session/sign-out"


@pytest.fixture
def authoriser(unit_of_work: FakeUnitOfWork, sink: FakeAuditSink, clock: FakeClock) -> Authoriser:
    return Authoriser(
        settings=AUTH_SETTINGS, unit_of_work=unit_of_work, audit_sink=sink, clock=clock
    )


def _active(roles: frozenset[Role]) -> ActiveSession:
    return ActiveSession(
        session_id="session-1",
        session=Session(
            user_subject="f3b2c1d0",
            username="j.jansen",
            keycloak_session_id="kc-sid-1",
            roles=roles,
            created_at=NOW,
            last_seen_at=NOW,
            expires_at=NOW + timedelta(hours=8),
            tokens=tokens(),
        ),
    )


async def _require(authoriser: Authoriser, roles: frozenset[Role]) -> None:
    await authoriser.require(
        _active(roles),
        Permission.SESSION_SIGN_OUT,
        action="sign-out",
        target=TARGET,
        client_ip=CLIENT_IP,
        correlation_id="c-1",
    )


@pytest.mark.parametrize("role", [Role.VIEWER, Role.OPERATOR])
async def test_a_permitted_user_passes_without_an_entry(
    authoriser: Authoriser, unit_of_work: FakeUnitOfWork, role: Role
) -> None:
    await _require(authoriser, frozenset({role}))

    assert unit_of_work.audit.entries == []


async def test_a_user_without_a_role_is_refused_and_recorded(
    authoriser: Authoriser, unit_of_work: FakeUnitOfWork
) -> None:
    with pytest.raises(AccessDeniedError) as raised:
        await _require(authoriser, frozenset())

    assert raised.value.reason is ReasonCode.NO_ROLE
    [entry] = unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "sign-out",
        Outcome.DENIED,
        ReasonCode.NO_ROLE,
    )
    assert entry.target == TARGET
    assert dict(entry.parameters) == {"permission": "session:sign-out"}
    assert entry.user_subject == "f3b2c1d0"
    assert entry.username == "j.jansen"
    assert entry.client_ip == CLIENT_IP
    assert entry.environment == ENVIRONMENT
    assert entry.occurred_at == NOW


async def test_a_missing_csrf_header_is_refused_and_recorded(
    authoriser: Authoriser, unit_of_work: FakeUnitOfWork
) -> None:
    with pytest.raises(AccessDeniedError) as raised:
        await authoriser.refuse_cross_site(
            _active(frozenset({Role.VIEWER})),
            action="sign-out",
            target=TARGET,
            client_ip=CLIENT_IP,
            correlation_id="c-1",
        )

    assert raised.value.reason is ReasonCode.CSRF
    [entry] = unit_of_work.audit.entries
    assert (entry.outcome, entry.reason, entry.target) == (Outcome.DENIED, ReasonCode.CSRF, TARGET)


async def test_a_refusal_stands_when_its_entry_cannot_be_stored(
    authoriser: Authoriser, unit_of_work: FakeUnitOfWork, sink: FakeAuditSink
) -> None:
    unit_of_work.audit.error = RuntimeError("insert privilege revoked")

    with pytest.raises(AccessDeniedError):
        await _require(authoriser, frozenset())

    [(entry, _error)] = sink.write_failures
    assert entry.reason is ReasonCode.NO_ROLE
