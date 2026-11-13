"""Keycloak's RP-initiated logout URL (task 7.6, design D2)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from podiumd_admin.adapters.oidc import KeycloakIdentityProvider
from podiumd_admin.ports.identity_provider import IdentityProvider
from tests.adapters.oidc.fake_keycloak import CLIENT_ID, ISSUER, FakeKeycloak

SIGNED_OUT = "https://admin.podiumd.onsdorp.example/signed-out"


def _parts(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    return f"{parts.scheme}://{parts.netloc}{parts.path}", query


def test_the_adapter_implements_the_port(identity_provider: KeycloakIdentityProvider) -> None:
    typed: IdentityProvider = identity_provider

    assert typed is identity_provider


async def test_the_url_carries_the_id_token_hint_and_the_redirect(
    identity_provider: KeycloakIdentityProvider,
) -> None:
    url = await identity_provider.end_session_url(
        id_token_hint="id-token-value",  # noqa: S106 - a test value, not a secret
        post_logout_redirect_uri=SIGNED_OUT,
    )

    endpoint, query = _parts(url)
    assert endpoint == f"{ISSUER}/protocol/openid-connect/logout"
    assert query == {
        "client_id": CLIENT_ID,
        "id_token_hint": "id-token-value",
        "post_logout_redirect_uri": SIGNED_OUT,
    }


async def test_without_an_id_token_the_client_id_identifies_the_client(
    identity_provider: KeycloakIdentityProvider,
) -> None:
    _endpoint, query = _parts(
        await identity_provider.end_session_url(
            id_token_hint=None, post_logout_redirect_uri=SIGNED_OUT
        )
    )

    assert query == {"client_id": CLIENT_ID, "post_logout_redirect_uri": SIGNED_OUT}


async def test_without_an_end_session_endpoint_the_user_goes_to_the_signed_out_page(
    identity_provider: KeycloakIdentityProvider, keycloak: FakeKeycloak
) -> None:
    document = keycloak.discovery()
    del document["end_session_endpoint"]
    keycloak.discovery = lambda: document  # type: ignore[method-assign]

    url = await identity_provider.end_session_url(
        id_token_hint="id-token-value",  # noqa: S106 - a test value, not a secret
        post_logout_redirect_uri=SIGNED_OUT,
    )

    assert url == SIGNED_OUT
