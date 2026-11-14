"""Refreshing the tokens of a Session (task 7.3).

Design D2 and D3: an expired access token is refreshed before the request is
authorised and the roles are read again from the new access token. Keycloak
refusing the refresh (``invalid_grant``: the user is disabled or their
Keycloak session ended) ends the Session; Keycloak being unreachable does not.
"""

from __future__ import annotations

from typing import Any

import pytest

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.ports.identity_provider import (
    IdentityProviderUnavailableError,
    RefreshRefusedError,
)
from tests.adapters.oidc.fake_keycloak import CLIENT_ID, FakeKeycloak


async def test_a_refresh_returns_new_tokens_and_the_current_roles(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.roles = ["operator"]

    identity = await identity_provider.refresh("refresh-token-1")

    assert identity.claims["resource_access"] == {CLIENT_ID: {"roles": ["operator"]}}
    assert identity.tokens.refresh_token == "refresh-token-value"  # noqa: S105
    [request] = [r for r in keycloak.requests if r.url.path.endswith("/token")]
    form = keycloak.form(request)
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "refresh-token-1"  # noqa: S105


async def test_a_refresh_without_an_id_token_is_accepted(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.include_id_token = False

    identity = await identity_provider.refresh("refresh-token-1")

    assert identity.tokens.id_token is None
    assert identity.username == "j.jansen"


async def test_a_refreshed_id_token_needs_no_nonce(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.nonce = None

    identity = await identity_provider.refresh("refresh-token-1")

    assert identity.tokens.id_token is not None


async def test_invalid_grant_is_a_refused_refresh(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.token_status = 400
    keycloak.token_error = "invalid_grant"  # noqa: S105 - an OAuth error code

    with pytest.raises(RefreshRefusedError) as raised:
        await identity_provider.refresh("refresh-token-1")

    assert "free text" not in str(raised.value)


@pytest.mark.parametrize("access_token_claims", [{"azp": "another-client"}, {"exp": 1_000_000}])
async def test_invalid_refreshed_tokens_are_a_refused_refresh(
    identity_provider: KeycloakIdentityProvider,
    keycloak: FakeKeycloak,
    access_token_claims: dict[str, Any],
) -> None:
    keycloak.access_token_claims = access_token_claims

    with pytest.raises(RefreshRefusedError):
        await identity_provider.refresh("refresh-token-1")


@pytest.mark.parametrize(("status", "error"), [(401, "invalid_client"), (503, None)])
async def test_other_errors_mean_keycloak_is_unavailable(
    identity_provider: KeycloakIdentityProvider,
    keycloak: FakeKeycloak,
    status: int,
    error: str | None,
) -> None:
    keycloak.token_status = status
    keycloak.token_error = error

    with pytest.raises(IdentityProviderUnavailableError):
        await identity_provider.refresh("refresh-token-1")


async def test_an_unreachable_keycloak_is_unavailable(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    keycloak.available = False

    with pytest.raises(IdentityProviderUnavailableError):
        await identity_provider.refresh("refresh-token-1")
