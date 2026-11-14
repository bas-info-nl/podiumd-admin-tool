"""The authentication flow against a real Keycloak (task 7.7, design D9).

A testcontainers Keycloak imports the shared development realm
(``dev/keycloak/podiumd-admin-realm.json``): client ``podiumd-admin`` with the
client roles ``viewer`` and ``operator``, and the users ``viewer``,
``operator`` and ``norole``. The app runs with the real Keycloak adapter and
in-memory fakes for the database, which has its own integration tests.

The tests sign in the way a browser does: the app's sign-in redirect, the
Keycloak login form, and the callback with the code Keycloak returns. They
then cover the refresh, a refusal after the user is disabled, sign-out with
Keycloak's logout, and back-channel logout: Keycloak posts the logout token
to a small server in this process, and the test hands it to the app.
"""

from __future__ import annotations

import html
import re
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from testcontainers.core.container import DockerContainer

from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.auth import AuthServices, auth_settings
from podiumd_admin.adapters.http.session import current_session
from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.adapters.system_clock import SystemClock
from podiumd_admin.application.authorisation import Authoriser
from podiumd_admin.application.sessions import ActiveSession, Sessions
from podiumd_admin.application.sign_in import SignIn
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import Outcome, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.ports.identity_provider import RefreshRefusedError
from tests.adapters.http.conftest import (
    BASE_URL,
    CLIENT_IP,
    SESSION_COOKIE,
    FakeReadiness,
    settings,
)
from tests.application.fakes import FakeAuditSink, FakeUnitOfWork

pytestmark = pytest.mark.integration

REPOSITORY_DIR = Path(__file__).resolve().parents[4]
REALM_FILE = REPOSITORY_DIR / "dev" / "keycloak" / "podiumd-admin-realm.json"
KEYCLOAK_IMAGE = (
    "quay.io/keycloak/keycloak:26.8.2"
    "@sha256:c68e286cacd87b942ac1939a0a1481461109d6acd3a57dc496969a319a76bbf0"
)
REALM = "podiumd"
CLIENT_ID = "podiumd-admin"
CLIENT_SECRET = "podiumd-admin-development-only"  # noqa: S105 - the public development secret
ADMIN_USER = "admin"
SIGNED_OUT = "https://admin.podiumd.onsdorp.example/signed-out"
CSRF_HEADER = {"X-PodiumD-Admin": "1"}


# --- Keycloak -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Keycloak:
    """The running Keycloak and an admin client for the realm."""

    url: str
    admin_password: str

    @property
    def issuer(self) -> str:
        return f"{self.url}/realms/{REALM}"

    def admin(self) -> httpx2.Client:
        token = httpx2.post(
            f"{self.url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": ADMIN_USER,
                "password": self.admin_password,
            },
        ).json()["access_token"]
        return httpx2.Client(
            base_url=f"{self.url}/admin/realms/{REALM}",
            headers={"Authorization": f"Bearer {token}"},
        )

    def user_id(self, username: str) -> str:
        with self.admin() as admin:
            [user] = admin.get("/users", params={"username": username, "exact": "true"}).json()
        return str(user["id"])

    def set_enabled(self, username: str, *, enabled: bool) -> None:
        user_id = self.user_id(username)
        with self.admin() as admin:
            admin.put(f"/users/{user_id}", json={"enabled": enabled}).raise_for_status()

    def log_out(self, username: str) -> None:
        """End every Keycloak session of the user, as an administrator can."""
        user_id = self.user_id(username)
        with self.admin() as admin:
            admin.post(f"/users/{user_id}/logout").raise_for_status()

    def set_backchannel_logout_url(self, url: str) -> None:
        with self.admin() as admin:
            [client] = admin.get("/clients", params={"clientId": CLIENT_ID}).json()
            client["attributes"]["backchannel.logout.url"] = url
            admin.put(f"/clients/{client['id']}", json=client).raise_for_status()


@pytest.fixture(scope="session")
def keycloak() -> Iterator[Keycloak]:
    password = secrets.token_hex(16)
    container = (
        DockerContainer(KEYCLOAK_IMAGE)
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", password)
        .with_volume_mapping(str(REALM_FILE), "/opt/keycloak/data/import/realm.json", "ro")
        .with_command("start-dev --import-realm")
        .with_exposed_ports(8080)
        # Lets Keycloak post back-channel logout tokens to this process.
        .with_kwargs(extra_hosts={"host.docker.internal": "host-gateway"})
    )
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8080)}"
        _wait_for_realm(url)
        yield Keycloak(url=url, admin_password=password)


def _wait_for_realm(url: str) -> None:
    """Wait until the imported realm answers its discovery document."""
    with httpx2.Client(timeout=5) as client:
        for _ in range(180):
            try:
                if client.get(f"{url}/realms/{REALM}/.well-known/openid-configuration").is_success:
                    return
            except httpx2.TransportError:
                pass
            threading.Event().wait(1)
    raise TimeoutError("Keycloak did not serve the realm within three minutes")


# --- The app --------------------------------------------------------------------------


@dataclass
class App:
    """The app wired to the real Keycloak, and the fakes behind it."""

    client: TestClient
    unit_of_work: FakeUnitOfWork
    identity_provider: KeycloakIdentityProvider


async def _probe(active: Annotated[ActiveSession, Depends(current_session)]) -> dict[str, Any]:
    return {"role": active.user.role}


@pytest.fixture
def app(keycloak: Keycloak) -> Iterator[App]:
    app_settings = settings(
        oidc_issuer=keycloak.issuer,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=CLIENT_SECRET,
    )
    sink = FakeAuditSink()
    clock = SystemClock()
    unit_of_work = FakeUnitOfWork(sink=sink)
    identity_provider = KeycloakIdentityProvider(
        issuer=keycloak.issuer, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
    )
    common: dict[str, Any] = {
        "settings": auth_settings(app_settings),
        "identity_provider": identity_provider,
        "unit_of_work": unit_of_work,
        "audit_sink": sink,
        "failures": UnauthenticatedFailureAggregator(sink=sink, clock=clock),
        "clock": clock,
    }
    services = AuthServices(
        sign_in=SignIn(**common),
        sessions=Sessions(**common),
        authoriser=Authoriser(
            settings=common["settings"], unit_of_work=unit_of_work, audit_sink=sink, clock=clock
        ),
    )
    web_app = create_app(app_settings, readiness=FakeReadiness(), auth=services)
    web_app.add_api_route("/api/v1/probe", _probe, methods=["GET"])
    with TestClient(
        web_app, base_url=BASE_URL, client=(CLIENT_IP, 50000), follow_redirects=False
    ) as client:
        yield App(client=client, unit_of_work=unit_of_work, identity_provider=identity_provider)


def _log_in_at_keycloak(authorization_url: str, username: str) -> str:
    """Fill in Keycloak's login form; return the query of the callback Keycloak redirects to.

    Keycloak marks its cookies ``Secure`` even over plain HTTP, so they are sent
    back by hand, as a browser on an HTTPS origin would.
    """
    with httpx2.Client(follow_redirects=False, timeout=10) as browser:
        page = browser.get(authorization_url)
        assert page.status_code == 200, page.text
        match = re.search(r'<form\b[^>]*\baction="([^"]+)"', page.text)
        assert match is not None, "no login form"
        cookies = "; ".join(f"{name}={value}" for name, value in page.cookies.items())
        login = browser.post(
            html.unescape(match[1]),
            data={"username": username, "password": username},
            headers={"Cookie": cookies},
        )
    assert login.status_code == 302, login.text
    callback = urlsplit(login.headers["location"])
    assert f"{callback.scheme}://{callback.netloc}{callback.path}" == f"{BASE_URL}/auth/callback"
    return callback.query


def _sign_in(app: App, username: str) -> httpx2.Response:
    """Sign in like a browser: app redirect, Keycloak login form, app callback."""
    start = app.client.get("/auth/sign-in", params={"return_to": "/audit-log"})
    assert start.status_code == 302
    query = _log_in_at_keycloak(start.headers["location"], username)
    return app.client.get(f"/auth/callback?{query}")


def _expire_access_token(app: App) -> None:
    """Make the stored access token look expired, so the next request refreshes it."""
    [(session_id, session)] = app.unit_of_work.sessions.sessions.items()
    assert session.tokens is not None
    expired = replace(
        session.tokens, access_token_expires_at=session.created_at - timedelta(seconds=1)
    )
    app.unit_of_work.sessions.sessions[session_id] = replace(session, tokens=expired)


# --- The code flow ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("username", "role"), [("viewer", Role.VIEWER), ("operator", Role.OPERATOR)]
)
def test_a_user_with_a_role_signs_in(app: App, username: str, role: Role) -> None:
    response = _sign_in(app, username)

    assert response.status_code == 302
    assert response.headers["location"] == "/audit-log"
    [session] = app.unit_of_work.sessions.sessions.values()
    assert session.roles == frozenset({role})
    assert session.username == username
    assert session.keycloak_session_id
    [entry] = app.unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.username) == ("sign-in", Outcome.ALLOWED, username)
    assert app.client.get("/api/v1/probe").json() == {"role": role.value}


def test_a_user_without_a_role_sees_no_access(app: App) -> None:
    response = _sign_in(app, "norole")

    assert response.headers["location"] == "/no-access"
    assert SESSION_COOKIE not in response.cookies
    assert app.unit_of_work.sessions.sessions == {}
    [entry] = app.unit_of_work.audit.entries
    assert (entry.outcome, entry.reason, entry.username) == (
        Outcome.DENIED,
        ReasonCode.NO_ROLE,
        "norole",
    )


def test_a_replayed_callback_creates_no_second_session(app: App) -> None:
    start = app.client.get("/auth/sign-in", params={"return_to": "/audit-log"})
    query = _log_in_at_keycloak(start.headers["location"], "viewer")
    sign_in_cookie = app.client.cookies.get("__Host-podiumd_admin_sign_in")

    first = app.client.get(f"/auth/callback?{query}")
    app.client.cookies.set("__Host-podiumd_admin_sign_in", sign_in_cookie or "")
    second = app.client.get(f"/auth/callback?{query}")

    assert first.headers["location"] == "/audit-log"
    assert urlsplit(second.headers["location"]).path == "/sign-in-error"
    assert len(app.unit_of_work.sessions.sessions) == 1


# --- Refresh ----------------------------------------------------------------------------


def test_an_expired_access_token_is_refreshed(app: App) -> None:
    _sign_in(app, "operator")
    [before] = app.unit_of_work.sessions.sessions.values()
    _expire_access_token(app)

    response = app.client.get("/api/v1/probe")

    assert response.json() == {"role": "operator"}
    [after] = app.unit_of_work.sessions.sessions.values()
    assert after.tokens is not None
    assert before.tokens is not None
    assert after.tokens.access_token != before.tokens.access_token
    assert after.tokens.access_token_expires_at > before.tokens.access_token_expires_at


def test_a_disabled_user_cannot_refresh(app: App, keycloak: Keycloak) -> None:
    _sign_in(app, "viewer")
    _expire_access_token(app)
    keycloak.set_enabled("viewer", enabled=False)
    try:
        response = app.client.get("/api/v1/probe")
    finally:
        keycloak.set_enabled("viewer", enabled=True)

    assert response.status_code == 401
    assert app.unit_of_work.sessions.sessions == {}
    assert [entry.reason for entry in app.unit_of_work.audit.entries] == [
        None,
        ReasonCode.REFRESH_REFUSED,
    ]


async def test_the_adapter_refuses_a_refresh_after_keycloak_logout(
    app: App, keycloak: Keycloak
) -> None:
    _sign_in(app, "viewer")
    [session] = app.unit_of_work.sessions.sessions.values()
    assert session.tokens is not None
    assert session.tokens.refresh_token is not None
    keycloak.log_out("viewer")

    with pytest.raises(RefreshRefusedError):
        await app.identity_provider.refresh(session.tokens.refresh_token)


# --- Sign-out ---------------------------------------------------------------------------


def test_sign_out_ends_the_session_here_and_in_keycloak(app: App, keycloak: Keycloak) -> None:
    _sign_in(app, "viewer")
    [session] = app.unit_of_work.sessions.sessions.values()
    assert session.tokens is not None
    refresh_token = session.tokens.refresh_token

    response = app.client.post("/api/v1/session/sign-out", headers=CSRF_HEADER)

    assert response.status_code == 200
    assert app.unit_of_work.sessions.sessions == {}
    with httpx2.Client(follow_redirects=False, timeout=10) as browser:
        logout = browser.get(response.json()["end_session_url"])
    assert logout.status_code == 302
    assert logout.headers["location"] == SIGNED_OUT
    # Keycloak's session has ended too: the refresh token no longer works.
    token = httpx2.post(
        f"{keycloak.issuer}/protocol/openid-connect/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    assert token.status_code == 400
    assert token.json()["error"] == "invalid_grant"


# --- Back-channel logout ----------------------------------------------------------------


@dataclass
class LogoutReceiver:
    """A small HTTP server that receives Keycloak's back-channel logout tokens."""

    tokens: list[str] = field(default_factory=list)
    received: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def logout_receiver() -> Iterator[tuple[LogoutReceiver, int]]:
    receiver = LogoutReceiver()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            form = parse_qs(self.rfile.read(length).decode())
            receiver.tokens.extend(form.get("logout_token", []))
            receiver.received.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            """Keep the test output clean."""

    # Bound to every interface, so the Keycloak container reaches it through
    # host.docker.internal; it only lives as long as this test.
    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)  # noqa: S104
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield receiver, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def test_back_channel_logout_ends_the_session(
    app: App, keycloak: Keycloak, logout_receiver: tuple[LogoutReceiver, int]
) -> None:
    receiver, port = logout_receiver
    keycloak.set_backchannel_logout_url(
        f"http://host.docker.internal:{port}/auth/backchannel-logout"
    )
    _sign_in(app, "viewer")
    [session] = app.unit_of_work.sessions.sessions.values()

    keycloak.log_out("viewer")
    assert receiver.received.wait(timeout=30), "Keycloak sent no logout token"
    [logout_token] = receiver.tokens
    response = app.client.post("/auth/backchannel-logout", data={"logout_token": logout_token})

    assert response.status_code == 200
    assert app.unit_of_work.sessions.sessions == {}
    [_sign_in_entry, entry] = app.unit_of_work.audit.entries
    assert (entry.action, entry.outcome, entry.reason) == (
        "session-expired",
        Outcome.INFO,
        ReasonCode.BACKCHANNEL_LOGOUT,
    )
    assert entry.user_subject == session.user_subject


def test_a_tampered_logout_token_is_refused(
    app: App, keycloak: Keycloak, logout_receiver: tuple[LogoutReceiver, int]
) -> None:
    receiver, port = logout_receiver
    keycloak.set_backchannel_logout_url(
        f"http://host.docker.internal:{port}/auth/backchannel-logout"
    )
    _sign_in(app, "viewer")
    keycloak.log_out("viewer")
    assert receiver.received.wait(timeout=30), "Keycloak sent no logout token"
    header, payload, signature = receiver.tokens[0].split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"

    response = app.client.post("/auth/backchannel-logout", data={"logout_token": tampered})

    assert response.status_code == 400
    assert len(app.unit_of_work.sessions.sessions) == 1
