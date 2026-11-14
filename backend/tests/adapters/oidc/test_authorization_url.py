"""The Keycloak sign-in URL, built with Authlib (task 7.1).

Design D2: the Authorization Code flow with PKCE (S256), with the ``state``
and ``nonce`` of the pre-auth record and the configured redirect URI.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError
from tests.adapters.oidc.fake_keycloak import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeKeycloak

REDIRECT_URI = "https://admin.podiumd.onsdorp.example/auth/callback"
VERIFIER = "v" * 43


def provider(keycloak: FakeKeycloak) -> KeycloakIdentityProvider:
    return KeycloakIdentityProvider(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        transport=keycloak.transport,
    )


async def test_the_url_asks_for_a_code_with_pkce_state_and_nonce() -> None:
    url = await provider(FakeKeycloak()).authorization_url(
        redirect_uri=REDIRECT_URI, state="state-1", nonce="nonce-1", code_verifier=VERIFIER
    )

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        f"{ISSUER}/protocol/openid-connect/auth"
    )
    assert query == {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid",
        "state": "state-1",
        "nonce": "nonce-1",
        "code_challenge": create_s256_code_challenge(VERIFIER),
        "code_challenge_method": "S256",
    }


async def test_the_discovery_document_is_fetched_once() -> None:
    keycloak = FakeKeycloak()
    identity_provider = provider(keycloak)

    for _ in range(3):
        await identity_provider.authorization_url(
            redirect_uri=REDIRECT_URI, state="s", nonce="n", code_verifier=VERIFIER
        )

    assert len(keycloak.requests) == 1


async def test_an_unreachable_keycloak_is_reported() -> None:
    keycloak = FakeKeycloak(available=False)

    with pytest.raises(IdentityProviderUnavailableError):
        await provider(keycloak).authorization_url(
            redirect_uri=REDIRECT_URI, state="s", nonce="n", code_verifier=VERIFIER
        )


async def test_a_discovery_document_for_another_issuer_is_refused() -> None:
    keycloak = FakeKeycloak()
    keycloak.discovery = lambda: {"issuer": "https://evil.example/realms/podiumd"}  # type: ignore[method-assign]

    with pytest.raises(IdentityProviderUnavailableError):
        await provider(keycloak).authorization_url(
            redirect_uri=REDIRECT_URI, state="s", nonce="n", code_verifier=VERIFIER
        )
