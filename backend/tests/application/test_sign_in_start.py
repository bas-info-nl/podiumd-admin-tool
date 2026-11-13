"""Starting a sign-in (task 7.1).

Spec: authentication, "Sign-in through the Environment's Keycloak" and "Safe
return after sign-in and sign-out". Design D2: a pre-auth record holds
``state``, ``nonce``, the PKCE verifier and the validated return path; the
redirect URI comes from the configured public hostname.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from podiumd_admin.application.sign_in import SignIn
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError
from tests.application.conftest import AUTH_SETTINGS, NOW, REDIRECT_URI
from tests.application.fakes import (
    AUTHORIZATION_ENDPOINT,
    FakeAuditSink,
    FakeClock,
    FakeIdentityProvider,
    FakeUnitOfWork,
)


@pytest.fixture
def sign_in(
    identity_provider: FakeIdentityProvider,
    unit_of_work: FakeUnitOfWork,
    sink: FakeAuditSink,
    failures: UnauthenticatedFailureAggregator,
    clock: FakeClock,
) -> SignIn:
    return SignIn(
        settings=AUTH_SETTINGS,
        identity_provider=identity_provider,
        unit_of_work=unit_of_work,
        audit_sink=sink,
        failures=failures,
        clock=clock,
    )


async def test_start_stores_a_pre_auth_record(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork
) -> None:
    started = await sign_in.start("/audit-log?outcome=denied")

    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    assert attempt.return_path == "/audit-log?outcome=denied"
    assert attempt.created_at == NOW
    assert len({attempt.state, attempt.nonce, attempt.code_verifier}) == 3
    assert unit_of_work.commits == 1


async def test_the_authorisation_url_carries_the_record_and_the_configured_redirect_uri(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork
) -> None:
    started = await sign_in.start("/")

    attempt = unit_of_work.sign_in_attempts.attempts[started.attempt_id]
    url = urlsplit(started.authorization_url)
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    assert started.authorization_url.startswith(AUTHORIZATION_ENDPOINT)
    assert query == {
        "redirect_uri": REDIRECT_URI,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "verifier": attempt.code_verifier,
    }


@pytest.mark.parametrize("return_path", ["//evil.example/", "https://evil.example/", None])
async def test_an_unsafe_return_path_becomes_the_start_page(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork, return_path: str | None
) -> None:
    started = await sign_in.start(return_path)

    assert unit_of_work.sign_in_attempts.attempts[started.attempt_id].return_path == "/"


async def test_every_attempt_gets_new_random_values(
    sign_in: SignIn, unit_of_work: FakeUnitOfWork
) -> None:
    first = await sign_in.start("/")
    second = await sign_in.start("/")

    one = unit_of_work.sign_in_attempts.attempts[first.attempt_id]
    two = unit_of_work.sign_in_attempts.attempts[second.attempt_id]
    assert first.attempt_id != second.attempt_id
    assert one.state != two.state
    assert one.nonce != two.nonce
    assert one.code_verifier != two.code_verifier
    assert len(first.attempt_id) >= 43


async def test_no_record_is_stored_when_keycloak_cannot_be_reached(
    sign_in: SignIn, identity_provider: FakeIdentityProvider, unit_of_work: FakeUnitOfWork
) -> None:
    identity_provider.unavailable = True

    with pytest.raises(IdentityProviderUnavailableError):
        await sign_in.start("/")

    assert unit_of_work.sign_in_attempts.attempts == {}
