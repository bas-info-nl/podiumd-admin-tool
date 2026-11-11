"""An app built by the factory, with fake ports, for the HTTP adapter tests."""

from __future__ import annotations

import dataclasses
import ipaddress
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from podiumd_admin.adapters.http import create_app
from podiumd_admin.config import Settings
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.domain.roles import RoleMapping
from podiumd_admin.domain.session_timeouts import SessionTimeouts

SETTINGS = Settings(
    environment=EnvironmentIdentity("Utrecht", Stage.ACCP, "Hosting BV"),
    public_hostname="admin.podiumd.utrecht.example",
    oidc_issuer="https://keycloak.utrecht.example/realms/podiumd",
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
