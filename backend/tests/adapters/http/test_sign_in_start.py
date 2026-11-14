"""``GET /auth/sign-in``: the start of the sign-in (task 7.1).

Spec: authentication, "Safe return after sign-in and sign-out": the redirect
URI sent to Keycloak is built from the configured public hostname, even when a
request carries a forged ``Host`` or ``X-Forwarded-Host`` header. Design D2:
the pre-auth record is bound to the browser by an ``__Host-`` cookie.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.adapters.http.conftest import SIGN_IN_COOKIE, AuthWorld
from tests.application.fakes import AUTHORIZATION_ENDPOINT

CONFIGURED_REDIRECT_URI = "https://admin.podiumd.onsdorp.example/auth/callback"


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def test_sign_in_redirects_to_keycloak_and_stores_the_attempt(
    auth_client: TestClient, world: AuthWorld
) -> None:
    response = auth_client.get("/auth/sign-in", params={"return_to": "/audit-log"})

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(AUTHORIZATION_ENDPOINT)
    (attempt_id, attempt), *others = world.unit_of_work.sign_in_attempts.attempts.items()
    assert others == []
    assert attempt.return_path == "/audit-log"
    assert _query(location)["state"] == attempt.state
    assert response.cookies[SIGN_IN_COOKIE] == attempt_id


def test_the_attempt_cookie_is_a_host_only_secure_cookie(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/sign-in")

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SIGN_IN_COOKIE}=")
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= attributes
    assert not any(attribute.startswith("domain") for attribute in attributes)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"X-Forwarded-Host": "evil.example"},
        {"Host": "evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http"},
    ],
)
def test_the_redirect_uri_comes_from_the_public_hostname(
    auth_client: TestClient, headers: dict[str, str]
) -> None:
    response = auth_client.get("/auth/sign-in", headers=headers)

    assert _query(response.headers["location"])["redirect_uri"] == CONFIGURED_REDIRECT_URI


@pytest.mark.parametrize("return_to", ["//evil.example/", "https://evil.example/"])
def test_an_unsafe_return_path_becomes_the_start_page(
    auth_client: TestClient, world: AuthWorld, return_to: str
) -> None:
    auth_client.get("/auth/sign-in", params={"return_to": return_to})

    [attempt] = world.unit_of_work.sign_in_attempts.attempts.values()
    assert attempt.return_path == "/"


def test_keycloak_unavailable_leads_to_the_sign_in_error_page(
    auth_client: TestClient, world: AuthWorld
) -> None:
    world.identity_provider.unavailable = True

    response = auth_client.get("/auth/sign-in")

    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.path == "/sign-in-error"
    assert not location.netloc
    assert _query(response.headers["location"])["correlation_id"]
    assert SIGN_IN_COOKIE not in response.cookies
