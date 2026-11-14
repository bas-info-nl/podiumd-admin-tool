"""Validating a back-channel logout token (task 7.5).

OpenID Connect Back-Channel Logout 1.0, section 2.6: the token is a signed
JWT from the configured issuer, for this client, with ``iat``, the
back-channel logout event and no ``nonce``. Design D2 matches sessions on
``sid``, so a token without one is refused.
"""

from __future__ import annotations

from typing import Any

import pytest
from joserfc.jwk import RSAKey

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.domain.identity import LogoutNotice
from podiumd_admin.ports.identity_provider import (
    IdentityProviderUnavailableError,
    InvalidLogoutTokenError,
)
from tests.adapters.oidc.fake_keycloak import FakeKeycloak


async def test_a_valid_logout_token_names_the_keycloak_session(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    notice = await identity_provider.verify_logout_token(keycloak.logout_token())

    assert notice == LogoutNotice("kc-sid-1")


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-client"},
        {"iss": "https://evil.example/realms/podiumd"},
        {"iat": None},
        {"exp": 1_000_000},
        {"events": None},
        {"events": {"http://schemas.openid.net/event/something-else": {}}},
        {"events": ["http://schemas.openid.net/event/backchannel-logout"]},
        {"nonce": "a-nonce"},
        {"sid": None},
        {"sid": ""},
    ],
)
async def test_an_invalid_logout_token_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak, claims: dict[str, Any]
) -> None:
    with pytest.raises(InvalidLogoutTokenError):
        await identity_provider.verify_logout_token(keycloak.logout_token(**claims))


async def test_a_logout_token_signed_with_another_key_is_refused(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    forged = keycloak.sign(
        {"iss": "x"}, key=RSAKey.generate_key(2048, {"kid": "key-1"}), typ="logout+jwt"
    )

    with pytest.raises(InvalidLogoutTokenError):
        await identity_provider.verify_logout_token(forged)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
async def test_garbage_is_refused(identity_provider: KeycloakIdentityProvider, token: str) -> None:
    with pytest.raises(InvalidLogoutTokenError):
        await identity_provider.verify_logout_token(token)


async def test_an_unreachable_keycloak_is_reported(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    token = keycloak.logout_token()
    keycloak.available = False

    with pytest.raises(IdentityProviderUnavailableError):
        await identity_provider.verify_logout_token(token)
