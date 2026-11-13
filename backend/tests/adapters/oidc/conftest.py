"""Fixtures for the OIDC adapter tests: a fake Keycloak and the adapter talking to it."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from tests.adapters.oidc.fake_keycloak import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeKeycloak
from tests.application.fakes import FakeClock


@pytest.fixture
def keycloak() -> FakeKeycloak:
    return FakeKeycloak()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def identity_provider(keycloak: FakeKeycloak, clock: FakeClock) -> KeycloakIdentityProvider:
    return KeycloakIdentityProvider(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        transport=keycloak.transport,
        clock=clock,
    )
