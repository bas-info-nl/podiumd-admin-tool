"""``POST /api/v1/session/sign-out`` (task 7.6).

Spec: authentication, "Sign-out" (including "Cross-site sign-out attempt");
access-control, "Actions are protected against cross-site requests" and
"Permission catalogue" (``session:sign-out``); audit-log, "No action without
an Audit Entry" (issue #30 included).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from podiumd_admin.adapters.db.unit_of_work import TransactionAbortedError
from podiumd_admin.adapters.http.openapi import openapi_document
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.adapters.http.conftest import CLIENT_IP, CSRF_HEADER, NOW, SESSION_COOKIE, AuthWorld
from tests.application.fakes import END_SESSION_ENDPOINT, tokens

PATH = "/api/v1/session/sign-out"
SESSION_ID = "session-id-from-the-cookie"


@pytest.fixture
def signed_in(auth_client: TestClient, world: AuthWorld) -> TestClient:
    _store(world, frozenset({Role.VIEWER}))
    auth_client.cookies.set(SESSION_COOKIE, SESSION_ID)
    return auth_client


def _store(world: AuthWorld, roles: frozenset[Role]) -> None:
    world.unit_of_work.sessions.sessions[SESSION_ID] = Session(
        user_subject="f3b2c1d0",
        username="j.jansen",
        keycloak_session_id="kc-sid-1",
        roles=roles,
        created_at=NOW,
        last_seen_at=NOW,
        expires_at=NOW + timedelta(hours=8),
        tokens=tokens(),
    )


def test_sign_out_ends_the_session_and_returns_the_keycloak_logout_url(
    signed_in: TestClient, world: AuthWorld
) -> None:
    response = signed_in.post(PATH, headers=CSRF_HEADER)

    assert response.status_code == 200
    url = response.json()["end_session_url"]
    assert url.startswith(END_SESSION_ENDPOINT)
    assert (
        "post_logout_redirect_uri=https%3A%2F%2Fadmin.podiumd.onsdorp.example%2Fsigned-out" in url
    )
    assert world.unit_of_work.sessions.sessions == {}
    [entry] = world.unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.client_ip) == (
        "sign-out",
        Outcome.ALLOWED,
        CLIENT_IP,
    )
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "max-age=0" in cookie.lower()


@pytest.mark.parametrize("headers", [{}, {"X-PodiumD-Admin": "0"}, {"X-PodiumD-Admin": "true"}])
def test_sign_out_without_the_csrf_header_is_refused(
    signed_in: TestClient, world: AuthWorld, headers: dict[str, str]
) -> None:
    response = signed_in.post(PATH, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"error": "access-denied"}
    assert SESSION_ID in world.unit_of_work.sessions.sessions
    [entry] = world.unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "sign-out",
        Outcome.DENIED,
        ReasonCode.CSRF,
    )
    assert entry.target == f"POST {PATH}"


def test_sign_out_without_a_role_is_refused(auth_client: TestClient, world: AuthWorld) -> None:
    _store(world, frozenset())
    auth_client.cookies.set(SESSION_COOKIE, SESSION_ID)

    response = auth_client.post(PATH, headers=CSRF_HEADER)

    assert response.status_code == 403
    assert SESSION_ID in world.unit_of_work.sessions.sessions
    [entry] = world.unit_of_work.audit.entries
    assert (entry.reason, dict(entry.parameters)) == (
        ReasonCode.NO_ROLE,
        {"permission": "session:sign-out"},
    )


def test_sign_out_without_a_session_gets_401(auth_client: TestClient, world: AuthWorld) -> None:
    response = auth_client.post(PATH, headers=CSRF_HEADER)

    assert response.status_code == 401
    assert world.unit_of_work.audit.entries == []


@pytest.mark.parametrize("failure", ["insert", "aborted"])
def test_the_session_is_kept_when_the_action_cannot_be_recorded(
    signed_in: TestClient, world: AuthWorld, failure: str
) -> None:
    if failure == "insert":
        world.unit_of_work.audit.error = RuntimeError("insert privilege revoked")
    else:
        world.unit_of_work.abort_error = TransactionAbortedError
        world.unit_of_work.abort_next_audited_commit = True

    response = signed_in.post(PATH, headers=CSRF_HEADER)

    assert response.status_code == 500
    assert response.json() == {"error": "action-not-recorded"}
    assert SESSION_ID in world.unit_of_work.sessions.sessions
    assert "set-cookie" not in response.headers


def test_sign_out_is_not_a_get(signed_in: TestClient) -> None:
    assert signed_in.get(PATH).status_code == 405


def test_sign_out_is_in_the_openapi_document() -> None:
    document: dict[str, Any] = openapi_document()

    operation = document["paths"][PATH]["post"]
    assert operation["operationId"] == "signOut"
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/SignOutResponse"}
    assert document["components"]["schemas"]["SignOutResponse"]["required"] == ["end_session_url"]
