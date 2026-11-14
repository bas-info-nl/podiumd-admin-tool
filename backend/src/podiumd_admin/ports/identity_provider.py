"""The IdentityProvider port: the Environment's Keycloak, as the application sees it.

Design D1 and D2. The OIDC adapter implements it with Authlib: the
Authorization Code flow with PKCE, token refresh, back-channel logout tokens
and RP-initiated logout. Every token it returns has been validated.

Errors carry no token values and no free text from Keycloak.
"""

from __future__ import annotations

from typing import Protocol

from podiumd_admin.domain.identity import LogoutNotice, VerifiedIdentity


class IdentityProviderUnavailableError(Exception):
    """Keycloak could not be reached or answered unexpectedly."""


class TokenExchangeError(Exception):
    """The authorisation code could not be exchanged for valid tokens."""


class RefreshRefusedError(Exception):
    """Keycloak refused to refresh the tokens: the user is disabled or their session ended."""


class InvalidLogoutTokenError(Exception):
    """A back-channel logout token is not a valid logout token for this client."""


class IdentityProvider(Protocol):
    """Signs users in and keeps their tokens fresh."""

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_verifier: str
    ) -> str:
        """The Keycloak sign-in URL, with the S256 challenge of ``code_verifier``.

        Raises ``IdentityProviderUnavailableError`` if Keycloak cannot be reached.
        """
        ...

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> VerifiedIdentity:
        """Exchange ``code`` for validated tokens; the ID token must carry ``nonce``.

        Raises ``TokenExchangeError`` if the exchange or the validation fails.
        """
        ...

    async def refresh(self, refresh_token: str) -> VerifiedIdentity:
        """New validated tokens for ``refresh_token``.

        Raises ``RefreshRefusedError`` if Keycloak refuses, and
        ``IdentityProviderUnavailableError`` if it cannot be reached.
        """
        ...

    async def verify_logout_token(self, logout_token: str) -> LogoutNotice:
        """Validate a back-channel logout token against Keycloak's JWKS.

        Raises ``InvalidLogoutTokenError`` if it is not valid for this client.
        """
        ...

    async def end_session_url(
        self, *, id_token_hint: str | None, post_logout_redirect_uri: str
    ) -> str:
        """Keycloak's ``end_session_endpoint`` URL for RP-initiated logout."""
        ...
