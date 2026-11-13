"""The request-time session dependency (task 7.3).

Spec: authentication, "Session lifetime and expiry": API requests on an ended
session get a 401 response; access-control, "Every request is authorised on
the server" (a request without a valid session is refused with 401 and
counted on stdout). Design D2: an expired access token is refreshed before
the request is authorised.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.session import current_session
from podiumd_admin.application.sessions import ActiveSession
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.adapters.http.conftest import (
    BASE_URL,
    CLIENT_IP,
    NOW,
    SESSION_COOKIE,
    SETTINGS,
    AuthWorld,
    FakeReadiness,
)
from tests.application.fakes import identity, tokens

SESSION_ID = "session-id-from-the-cookie"
SUBJECT = "f3b2c1d0-0000-4000-8000-000000000001"


async def probe(active: Annotated[ActiveSession, Depends(current_session)]) -> dict[str, Any]:
    return {"subject": active.user.subject, "role": active.user.role}


@pytest.fixture
def client(world: AuthWorld) -> Iterator[TestClient]:
    app = create_app(SETTINGS, readiness=FakeReadiness(), auth=world.services)
    app.add_api_route("/api/v1/probe", probe, methods=["GET"])
    with TestClient(app, base_url=BASE_URL, client=(CLIENT_IP, 50000)) as test_client:
        yield test_client


def _store(world: AuthWorld, **overrides: Any) -> None:
    fields: dict[str, Any] = {
        "user_subject": SUBJECT,
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER}),
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(hours=8),
        "tokens": tokens(expires_at=NOW + timedelta(minutes=5)),
    }
    fields.update(overrides)
    world.unit_of_work.sessions.sessions[SESSION_ID] = Session(**fields)


def test_a_valid_session_reaches_the_handler(client: TestClient, world: AuthWorld) -> None:
    _store(world)
    client.cookies.set(SESSION_COOKIE, SESSION_ID)

    response = client.get("/api/v1/probe")

    assert response.status_code == 200
    assert response.json() == {"subject": SUBJECT, "role": "viewer"}


@pytest.mark.parametrize("cookie", [None, "never-issued"])
def test_a_request_without_a_valid_session_gets_401(
    client: TestClient, world: AuthWorld, cookie: str | None
) -> None:
    if cookie is not None:
        client.cookies.set(SESSION_COOKIE, cookie)

    response = client.get("/api/v1/probe")

    assert response.status_code == 401
    assert response.json() == {"error": "not-signed-in"}
    assert response.headers["cache-control"] == "no-store"
    assert world.unit_of_work.audit.entries == []
    world.failures.flush_all()
    assert [(line.client_ip, line.reason) for line in world.sink.summaries] == [
        (CLIENT_IP, ReasonCode.NO_SESSION)
    ]


def test_an_idle_session_ends_with_401_and_one_entry(client: TestClient, world: AuthWorld) -> None:
    _store(world)
    world.clock.advance(timedelta(minutes=30))
    client.cookies.set(SESSION_COOKIE, SESSION_ID)

    first = client.get("/api/v1/probe")
    second = client.get("/api/v1/probe")

    assert (first.status_code, second.status_code) == (401, 401)
    [entry] = world.unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "session-expired",
        Outcome.INFO,
        ReasonCode.IDLE,
    )
    assert entry.client_ip == CLIENT_IP


def test_an_ended_session_clears_the_cookie(client: TestClient, world: AuthWorld) -> None:
    client.cookies.set(SESSION_COOKIE, "never-issued")

    response = client.get("/api/v1/probe")

    [cookie] = response.headers.get_list("set-cookie")
    assert cookie.startswith(f'{SESSION_COOKIE}=""') or cookie.startswith(f"{SESSION_COOKIE}=;")
    assert "max-age=0" in cookie.lower()


def test_an_expired_access_token_is_refreshed_before_the_handler_runs(
    client: TestClient, world: AuthWorld
) -> None:
    _store(world)
    world.clock.advance(timedelta(minutes=6))
    world.identity_provider.refreshed = identity(
        ["operator"], session_tokens=tokens(world.clock.now() + timedelta(minutes=5), "2")
    )
    client.cookies.set(SESSION_COOKIE, SESSION_ID)

    response = client.get("/api/v1/probe")

    assert response.json() == {"subject": SUBJECT, "role": "operator"}


def test_a_refused_refresh_ends_the_session_with_401(client: TestClient, world: AuthWorld) -> None:
    _store(world)
    world.clock.advance(timedelta(minutes=6))
    world.identity_provider.refresh_refused = True
    client.cookies.set(SESSION_COOKIE, SESSION_ID)

    response = client.get("/api/v1/probe")

    assert response.status_code == 401
    [entry] = world.unit_of_work.audit.entries
    assert entry.reason is ReasonCode.REFRESH_REFUSED
    assert world.unit_of_work.sessions.sessions == {}


def test_an_unreachable_keycloak_gives_503_and_keeps_the_session(
    client: TestClient, world: AuthWorld
) -> None:
    _store(world)
    world.clock.advance(timedelta(minutes=6))
    world.identity_provider.unavailable = True
    client.cookies.set(SESSION_COOKIE, SESSION_ID)

    response = client.get("/api/v1/probe")

    assert response.status_code == 503
    assert response.json() == {"error": "identity-provider-unavailable"}
    assert SESSION_ID in world.unit_of_work.sessions.sessions
