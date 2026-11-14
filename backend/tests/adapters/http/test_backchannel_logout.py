"""``POST /auth/backchannel-logout``: Keycloak ends a user's sessions (task 7.5).

OpenID Connect Back-Channel Logout 1.0, section 2.8: the logout token comes as
an ``application/x-www-form-urlencoded`` ``logout_token`` parameter; the
answer is 200 on success and 400 for an invalid request, never cached.
Keycloak calls this endpoint itself, so it needs no CSRF header (design D2).
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from podiumd_admin.adapters.http.openapi import openapi_document
from podiumd_admin.domain.audit import ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.adapters.http.conftest import CLIENT_IP, NOW, AuthWorld
from tests.application.fakes import tokens

PATH = "/auth/backchannel-logout"


def _store(world: AuthWorld, session_id: str, sid: str) -> None:
    world.unit_of_work.sessions.sessions[session_id] = Session(
        user_subject="f3b2c1d0",
        username="j.jansen",
        keycloak_session_id=sid,
        roles=frozenset({Role.VIEWER}),
        created_at=NOW,
        last_seen_at=NOW,
        expires_at=NOW + timedelta(hours=8),
        tokens=tokens(),
    )


def test_a_valid_logout_token_ends_the_matching_sessions(
    auth_client: TestClient, world: AuthWorld
) -> None:
    world.identity_provider.logout_sid = "kc-sid-1"
    _store(world, "tab-1", "kc-sid-1")
    _store(world, "other", "kc-sid-2")

    response = auth_client.post(PATH, data={"logout_token": "valid-logout-token"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(world.unit_of_work.sessions.sessions) == {"other"}
    [entry] = world.unit_of_work.audit.entries
    assert entry.reason is ReasonCode.BACKCHANNEL_LOGOUT


def test_an_invalid_logout_token_gets_400_and_ends_nothing(
    auth_client: TestClient, world: AuthWorld
) -> None:
    world.identity_provider.logout_sid = "kc-sid-1"
    _store(world, "tab-1", "kc-sid-1")

    response = auth_client.post(PATH, data={"logout_token": "forged"})

    assert response.status_code == 400
    assert response.json() == {"error": "invalid-logout-token"}
    assert response.headers["cache-control"] == "no-store"
    assert "tab-1" in world.unit_of_work.sessions.sessions
    world.failures.flush_all()
    assert [(line.client_ip, line.reason) for line in world.sink.summaries] == [
        (CLIENT_IP, ReasonCode.INVALID_LOGOUT_TOKEN)
    ]


def test_a_request_without_a_logout_token_gets_400(auth_client: TestClient) -> None:
    assert auth_client.post(PATH, data={}).status_code == 400
    assert auth_client.post(PATH, json={"logout_token": "valid-logout-token"}).status_code == 400


def test_an_oversized_request_gets_400(auth_client: TestClient, world: AuthWorld) -> None:
    world.identity_provider.logout_sid = "kc-sid-1"

    response = auth_client.post(PATH, data={"logout_token": "x" * 100_000})

    assert response.status_code == 400


def test_the_endpoint_stays_out_of_the_openapi_document() -> None:
    assert PATH not in openapi_document()["paths"]
