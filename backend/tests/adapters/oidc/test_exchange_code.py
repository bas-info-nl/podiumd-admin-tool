"""Exchanging the authorisation code for validated tokens (task 7.2).

Design D2: the backend is a confidential client using the Authorization Code
flow with PKCE. Every token is validated before the application sees it:
signature (the realm's JWKS), issuer, audience, expiry and the nonce of the
pre-auth record. A failure never reveals Keycloak's free text.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

import pytest
from joserfc.jwk import RSAKey

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.ports.identity_provider import TokenExchangeError
from tests.adapters.oidc.fake_keycloak import (
    CLIENT_ID,
    CLIENT_SECRET,
    SUBJECT,
    FakeKeycloak,
)
from tests.application.fakes import FakeClock

REDIRECT_URI = "https://admin.podiumd.onsdorp.example/auth/callback"
VERIFIER = "v" * 43
NONCE = "nonce-of-the-attempt"


async def _exchange(identity_provider: KeycloakIdentityProvider) -> Any:
    return await identity_provider.exchange_code(
        code="code-1", redirect_uri=REDIRECT_URI, code_verifier=VERIFIER, nonce=NONCE
    )


async def test_the_exchange_returns_the_validated_identity(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak, clock: FakeClock
) -> None:
    keycloak.nonce = NONCE

    identity = await _exchange(identity_provider)

    assert identity.subject == SUBJECT
    assert identity.username == "j.jansen"
    assert identity.keycloak_session_id == "kc-sid-1"
    assert identity.claims["resource_access"] == {CLIENT_ID: {"roles": ["viewer"]}}
    assert identity.tokens.refresh_token == "refresh-token-value"  # noqa: S105
    assert identity.tokens.id_token is not None
    assert identity.tokens.access_token_expires_at == clock.now() + timedelta(seconds=300)


async def test_the_token_request_proves_the_verifier_and_authenticates_the_client(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.nonce = NONCE

    await _exchange(identity_provider)

    [request] = [r for r in keycloak.requests if r.url.path.endswith("/token")]
    assert keycloak.form(request) == {
        "grant_type": "authorization_code",
        "code": "code-1",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": VERIFIER,
    }
    credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {credentials}"


@pytest.mark.parametrize(
    "id_token_claims",
    [
        {"nonce": "another-nonce"},
        {"nonce": None},
        {"aud": "another-client"},
        {"aud": [CLIENT_ID, "another-client"], "azp": "another-client"},
        {"iss": "https://evil.example/realms/podiumd"},
        {"exp": 1_000_000},
        {"sub": "another-subject"},
    ],
)
async def test_an_invalid_id_token_is_refused(
    identity_provider: KeycloakIdentityProvider,
    keycloak: FakeKeycloak,
    id_token_claims: dict[str, Any],
) -> None:
    keycloak.nonce = NONCE
    keycloak.id_token_claims = id_token_claims

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


@pytest.mark.parametrize(
    "access_token_claims",
    [
        {"azp": "another-client"},
        {"iss": "https://evil.example/realms/podiumd"},
        {"exp": 1_000_000},
        {"sub": "another-subject"},
    ],
)
async def test_an_invalid_access_token_is_refused(
    identity_provider: KeycloakIdentityProvider,
    keycloak: FakeKeycloak,
    access_token_claims: dict[str, Any],
) -> None:
    keycloak.nonce = NONCE
    keycloak.access_token_claims = access_token_claims

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


async def test_a_token_signed_with_another_key_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.nonce = NONCE
    published = keycloak.key
    keycloak.key = RSAKey.generate_key(2048, {"kid": "key-1"})
    # The JWKS still publishes the old key, the tokens are signed with the new one.
    keycloak.discovery_keys = [published]

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


async def test_a_token_without_a_signature_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.nonce = NONCE
    unsigned = keycloak.id_token().rsplit(".", 1)[0] + "."
    keycloak.id_token = lambda **_: unsigned  # type: ignore[method-assign]

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


async def test_a_response_without_an_id_token_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.include_id_token = False

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


async def test_an_error_response_is_refused_without_its_free_text(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.token_status = 400
    keycloak.token_error = "invalid_grant"  # noqa: S105 - an OAuth error code

    with pytest.raises(TokenExchangeError) as raised:
        await _exchange(identity_provider)

    assert "free text" not in str(raised.value)
    assert raised.value.__cause__ is None or "free text" not in str(raised.value.__cause__)


@pytest.mark.parametrize("status", [500, 502])
async def test_a_server_error_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak, status: int
) -> None:
    keycloak.token_status = status

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)


async def test_an_unreachable_keycloak_is_a_failed_exchange(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.available = False

    with pytest.raises(TokenExchangeError):
        await _exchange(identity_provider)
