"""The Environment's Keycloak as ``IdentityProvider``, with Authlib (design D1, D2).

- The Authorization Code flow with PKCE (S256) and a confidential client,
  through Authlib's ``AsyncOAuth2Client``.
- The realm's endpoints come from its discovery document, fetched once; its
  ``issuer`` must be the configured issuer.

Errors never carry token values or Keycloak's free-text ``error_description``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final

import httpx2
from authlib.integrations.httpx_client import AsyncOAuth2Client

from podiumd_admin.ports.identity_provider import IdentityProviderUnavailableError

DEFAULT_TIMEOUT_SECONDS: Final = 10.0
SCOPE: Final = "openid"


@dataclass(frozen=True, slots=True)
class _Endpoints:
    authorization: str
    token: str
    jwks: str
    end_session: str | None


class KeycloakIdentityProvider:
    """Implements ``IdentityProvider`` for one Keycloak realm and one confidential client."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._timeout = timeout
        self._endpoints: _Endpoints | None = None
        self._lock = asyncio.Lock()

    def _client(self, **kwargs: Any) -> Any:
        """A new Authlib client; Authlib has no type hints, hence ``Any``."""
        options: dict[str, Any] = {"timeout": self._timeout}
        if self._transport is not None:
            options["transport"] = self._transport
        return AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_endpoint_auth_method="client_secret_basic",  # noqa: S106 - a method name
            scope=SCOPE,
            code_challenge_method="S256",
            **options,
            **kwargs,
        )

    async def _get_json(self, url: str) -> Any:
        try:
            async with httpx2.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except (httpx2.HTTPError, ValueError):
            raise IdentityProviderUnavailableError(
                f"Keycloak did not answer {url} as expected"
            ) from None

    async def _discover(self) -> _Endpoints:
        async with self._lock:
            if self._endpoints is not None:
                return self._endpoints
            document = await self._get_json(f"{self._issuer}/.well-known/openid-configuration")
            if not isinstance(document, dict) or document.get("issuer") != self._issuer:
                raise IdentityProviderUnavailableError(
                    "the discovery document does not belong to the configured issuer"
                )
            try:
                endpoints = _Endpoints(
                    authorization=_url(document, "authorization_endpoint"),
                    token=_url(document, "token_endpoint"),
                    jwks=_url(document, "jwks_uri"),
                    end_session=(
                        _url(document, "end_session_endpoint")
                        if "end_session_endpoint" in document
                        else None
                    ),
                )
            except ValueError as error:
                raise IdentityProviderUnavailableError(str(error)) from None
            self._endpoints = endpoints
            return endpoints

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_verifier: str
    ) -> str:
        endpoints = await self._discover()
        async with self._client(redirect_uri=redirect_uri) as client:
            url, _state = client.create_authorization_url(
                endpoints.authorization, state=state, nonce=nonce, code_verifier=code_verifier
            )
        return str(url)


def _url(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ValueError(f"the discovery document has no valid {name}")
    return value
