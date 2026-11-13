"""An app built by the factory, with fake ports, for the HTTP adapter tests.

``auth_client`` is an app with the authentication use cases wired to fakes;
``world`` holds those fakes, so a test can arrange and inspect them.
"""

from __future__ import annotations

import dataclasses
import ipaddress
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.auth import AuthServices, auth_settings
from podiumd_admin.application.sessions import Sessions
from podiumd_admin.application.sign_in import SignIn
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.config import Settings
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.domain.roles import RoleMapping
from podiumd_admin.domain.session_timeouts import SessionTimeouts
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
)

SETTINGS = Settings(
    environment=EnvironmentIdentity("Onsdorp", Stage.ACCP, "Hosting BV"),
    public_hostname="admin.podiumd.onsdorp.example",
    oidc_issuer="https://keycloak.onsdorp.example/realms/podiumd",
    oidc_client_id="podiumd-admin",
    oidc_client_secret=SecretStr("client-secret-value"),
    role_mapping=RoleMapping.for_client("podiumd-admin"),
    database_app_url=SecretStr(
        "postgresql+psycopg://podiumd_admin_app:app-password@db:5432/podiumd_admin"
    ),
    session_encryption_keys=(SecretStr(Fernet.generate_key().decode()),),
    session_timeouts=SessionTimeouts(),
    trusted_proxies=(ipaddress.ip_network("10.0.0.0/8"),),
)


def settings(**overrides: Any) -> Settings:
    return dataclasses.replace(SETTINGS, **overrides)


class FakeReadiness:
    """A readiness check whose answer a test sets."""

    def __init__(self) -> None:
        self.ready = True
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return self.ready


@pytest.fixture
def readiness() -> FakeReadiness:
    return FakeReadiness()


@pytest.fixture
def client(readiness: FakeReadiness) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, readiness=readiness)) as test_client:
        yield test_client


NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
BASE_URL = "https://admin.podiumd.onsdorp.example"
CLIENT_IP = "192.0.2.10"
SESSION_COOKIE = "__Host-podiumd_admin_session"
SIGN_IN_COOKIE = "__Host-podiumd_admin_sign_in"
CSRF_HEADER = {"X-PodiumD-Admin": "1"}


@dataclass
class AuthWorld:
    """The fakes behind the app, so a test can arrange and inspect them."""

    clock: FakeClock
    sink: FakeAuditSink
    unit_of_work: FakeUnitOfWork
    identity_provider: FakeIdentityProvider
    failures: UnauthenticatedFailureAggregator
    services: AuthServices


@pytest.fixture
def world() -> AuthWorld:
    clock = FakeClock(NOW)
    sink = FakeAuditSink()
    unit_of_work = FakeUnitOfWork(sink=sink)
    identity_provider = FakeIdentityProvider()
    failures = UnauthenticatedFailureAggregator(sink=sink, clock=clock)
    common: dict[str, Any] = {
        "settings": auth_settings(SETTINGS),
        "identity_provider": identity_provider,
        "unit_of_work": unit_of_work,
        "audit_sink": sink,
        "failures": failures,
        "clock": clock,
    }
    services = AuthServices(sign_in=SignIn(**common), sessions=Sessions(**common))
    return AuthWorld(clock, sink, unit_of_work, identity_provider, failures, services)


@pytest.fixture
def auth_client(world: AuthWorld) -> Iterator[TestClient]:
    app = create_app(SETTINGS, readiness=FakeReadiness(), auth=world.services)
    with TestClient(
        app, base_url=BASE_URL, client=(CLIENT_IP, 50000), follow_redirects=False
    ) as test_client:
        yield test_client
