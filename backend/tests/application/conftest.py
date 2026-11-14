"""Shared fixtures for the authentication use cases: fakes wired as the app wires adapters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from podiumd_admin.application.authentication import AuthSettings
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.domain.roles import RoleMapping
from podiumd_admin.domain.session_timeouts import SessionTimeouts
from tests.application.fakes import (
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
)

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
ENVIRONMENT = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.ACCP)
REDIRECT_URI = "https://admin.podiumd.onsdorp.example/auth/callback"
POST_LOGOUT_REDIRECT_URI = "https://admin.podiumd.onsdorp.example/signed-out"
CLIENT_IP = "192.0.2.10"

AUTH_SETTINGS = AuthSettings(
    environment=ENVIRONMENT,
    role_mapping=RoleMapping.for_client("podiumd-admin"),
    timeouts=SessionTimeouts(),
    redirect_uri=REDIRECT_URI,
    post_logout_redirect_uri=POST_LOGOUT_REDIRECT_URI,
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def sink() -> FakeAuditSink:
    return FakeAuditSink()


@pytest.fixture
def unit_of_work(sink: FakeAuditSink) -> FakeUnitOfWork:
    return FakeUnitOfWork(sink=sink)


@pytest.fixture
def identity_provider() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest.fixture
def failures(sink: FakeAuditSink, clock: FakeClock) -> UnauthenticatedFailureAggregator:
    return UnauthenticatedFailureAggregator(sink=sink, clock=clock)
