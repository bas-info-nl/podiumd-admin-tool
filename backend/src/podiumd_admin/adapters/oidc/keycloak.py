"""The Environment's Keycloak as ``IdentityProvider``, with Authlib (design D1, D2).

- The Authorization Code flow with PKCE (S256) and a confidential client,
  through Authlib's ``AsyncOAuth2Client``.
- The realm's endpoints come from its discovery document, fetched once; its
  ``issuer`` must be the configured issuer.
- Every token is validated with joserfc against the realm's JWKS before the
  application sees it: signature (asymmetric algorithms only), issuer,
  expiry, and per token type the audience, authorised party and nonce. The
  JWKS is fetched again when a token does not verify, at most once per
  ``JWKS_REFRESH_INTERVAL``, so a key rotation in Keycloak is picked up and a
  stream of forged tokens cannot make the adapter hammer Keycloak.
- The roles are read from the access token (design D3); Keycloak's client
  roles mapper puts them there by default.

Errors never carry token values or Keycloak's free-text ``error_description``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import httpx2
from authlib.integrations.base_client import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from podiumd_admin.adapters.system_clock import SystemClock
from podiumd_admin.domain.identity import LogoutNotice, VerifiedIdentity
from podiumd_admin.domain.session import SessionTokens
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.identity_provider import (
    IdentityProviderUnavailableError,
    InvalidLogoutTokenError,
    RefreshRefusedError,
    TokenExchangeError,
)

DEFAULT_TIMEOUT_SECONDS: Final = 10.0
SCOPE: Final = "openid"
LEEWAY_SECONDS: Final = 30
"""Clock skew tolerated between this instance and Keycloak."""
JWKS_REFRESH_INTERVAL: Final = timedelta(minutes=1)
ALGORITHMS: Final = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
)
"""Asymmetric signature algorithms only: never ``none`` or a shared-secret HMAC."""
BACKCHANNEL_LOGOUT_EVENT: Final = "http://schemas.openid.net/event/backchannel-logout"


class _InvalidTokenError(Exception):
    """A token failed validation. Carries no token value."""


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
        clock: Clock | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._timeout = timeout
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._endpoints: _Endpoints | None = None
        self._lock = asyncio.Lock()
        self._keys: KeySet | None = None
        self._keys_fetched_at: datetime | None = None
        self._keys_lock = asyncio.Lock()

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

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> VerifiedIdentity:
        try:
            endpoints = await self._discover()
            async with self._client(redirect_uri=redirect_uri) as client:
                token = await client.fetch_token(
                    endpoints.token,
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=code_verifier,
                )
            return await self._identity(dict(token), nonce=nonce)
        except (
            OAuthError,
            httpx2.HTTPError,
            IdentityProviderUnavailableError,
            _InvalidTokenError,
        ) as error:
            # Not chained: an OAuthError holds Keycloak's free text.
            raise TokenExchangeError(
                f"the authorisation code could not be exchanged ({type(error).__name__})"
            ) from None

    async def refresh(self, refresh_token: str) -> VerifiedIdentity:
        endpoints = await self._discover()
        try:
            async with self._client() as client:
                token = await client.refresh_token(endpoints.token, refresh_token=refresh_token)
        except OAuthError as error:
            # Not chained: an OAuthError holds Keycloak's free text.
            if error.error == "invalid_grant":
                raise RefreshRefusedError("Keycloak refused to refresh the tokens") from None
            raise IdentityProviderUnavailableError(
                f"Keycloak answered the refresh with {error.error!r}"
            ) from None
        except httpx2.HTTPError:
            raise IdentityProviderUnavailableError(
                "Keycloak could not refresh the tokens"
            ) from None
        try:
            return await self._identity(dict(token), nonce=None, id_token_required=False)
        except _InvalidTokenError:
            raise RefreshRefusedError("the refreshed tokens are not valid") from None

    async def verify_logout_token(self, logout_token: str) -> LogoutNotice:
        """Validate a logout token (OpenID Connect Back-Channel Logout 1.0, section 2.6).

        Raises ``IdentityProviderUnavailableError`` if the JWKS cannot be fetched.
        """
        try:
            claims = await self._claims(logout_token)
            self._check(
                claims,
                aud={"essential": True, "value": self._client_id},
                iat={"essential": True},
                sid={"essential": True},
            )
        except _InvalidTokenError:
            raise InvalidLogoutTokenError("the logout token is not valid") from None
        events = claims.get("events")
        if not isinstance(events, dict) or BACKCHANNEL_LOGOUT_EVENT not in events:
            raise InvalidLogoutTokenError("the logout token has no back-channel logout event")
        if "nonce" in claims:
            raise InvalidLogoutTokenError("a logout token must not carry a nonce")
        sid = claims.get("sid")
        if not isinstance(sid, str) or not sid.strip():
            raise InvalidLogoutTokenError("the logout token names no Keycloak session")
        return LogoutNotice(sid)

    async def _identity(
        self, token: Mapping[str, Any], *, nonce: str | None, id_token_required: bool = True
    ) -> VerifiedIdentity:
        """Validate a token response and build the identity it vouches for."""
        access_token = _text(token, "access_token")
        access_claims = await self._claims(access_token)
        self._check(
            access_claims,
            sub={"essential": True},
            azp={"essential": True, "value": self._client_id},
        )

        id_token = token.get("id_token")
        if id_token is None and id_token_required:
            raise _InvalidTokenError("the token response holds no ID token")
        id_claims: Mapping[str, Any] = {}
        if id_token is not None:
            id_claims = await self._claims(_text(token, "id_token"))
            options: dict[str, Any] = {
                "sub": {"essential": True, "value": access_claims["sub"]},
                "aud": {"essential": True, "value": self._client_id},
                "iat": {"essential": True},
            }
            if nonce is not None:
                options["nonce"] = {"essential": True, "value": nonce}
            self._check(id_claims, **options)
            audience = id_claims["aud"]
            several = isinstance(audience, list) and len(audience) > 1
            if (several or "azp" in id_claims) and id_claims.get("azp") != self._client_id:
                raise _InvalidTokenError("the ID token was issued to another party")

        refresh_token = token.get("refresh_token")
        return VerifiedIdentity(
            subject=access_claims["sub"],
            username=_claim(id_claims, access_claims, "preferred_username"),
            keycloak_session_id=_claim(id_claims, access_claims, "sid"),
            tokens=SessionTokens(
                access_token=access_token,
                refresh_token=refresh_token if isinstance(refresh_token, str) else None,
                id_token=id_token if isinstance(id_token, str) else None,
                access_token_expires_at=self._expires_at(token, access_claims),
            ),
            claims=access_claims,
        )

    def _expires_at(self, token: Mapping[str, Any], claims: Mapping[str, Any]) -> datetime:
        expires_in = token.get("expires_in")
        if isinstance(expires_in, int) and not isinstance(expires_in, bool) and expires_in > 0:
            return self._clock.now() + timedelta(seconds=expires_in)
        return datetime.fromtimestamp(int(claims["exp"]), tz=self._clock.now().tzinfo)

    def _check(self, claims: Mapping[str, Any], **options: Any) -> None:
        """Validate the issuer, the expiry and the given claims."""
        registry = JWTClaimsRegistry(
            now=int(self._clock.now().timestamp()),
            leeway=LEEWAY_SECONDS,
            iss={"essential": True, "value": self._issuer},
            exp={"essential": True},
            **options,
        )
        try:
            registry.validate(dict(claims))
        except JoseError:
            raise _InvalidTokenError("a token claim is missing or invalid") from None

    async def _claims(self, token: str) -> dict[str, Any]:
        """The claims of ``token`` once its signature verifies against the realm's JWKS."""
        keys = await self._key_set()
        try:
            return dict(jwt.decode(token, keys, algorithms=list(ALGORITHMS)).claims)
        except (JoseError, ValueError):
            pass
        refreshed = await self._key_set(refresh=True)
        if refreshed is keys:
            raise _InvalidTokenError("the token signature does not verify")
        try:
            return dict(jwt.decode(token, refreshed, algorithms=list(ALGORITHMS)).claims)
        except (JoseError, ValueError):
            raise _InvalidTokenError("the token signature does not verify") from None

    async def _key_set(self, *, refresh: bool = False) -> KeySet:
        """The realm's JWKS; fetched again on ``refresh`` if the last fetch is old enough."""
        async with self._keys_lock:
            now = self._clock.now()
            stale = (
                self._keys_fetched_at is None
                or now - self._keys_fetched_at >= JWKS_REFRESH_INTERVAL
            )
            if self._keys is not None and not (refresh and stale):
                return self._keys
            endpoints = await self._discover()
            document = await self._get_json(endpoints.jwks)
            try:
                keys = KeySet.import_key_set(document)
            except (JoseError, ValueError, TypeError, KeyError):
                raise IdentityProviderUnavailableError("the realm's JWKS is not valid") from None
            self._keys = keys
            self._keys_fetched_at = now
            return keys


def _text(token: Mapping[str, Any], name: str) -> str:
    value = token.get(name)
    if not isinstance(value, str) or not value:
        raise _InvalidTokenError(f"the token response holds no {name}")
    return value


def _claim(first: Mapping[str, Any], second: Mapping[str, Any], name: str) -> str | None:
    """A text claim from the first token that has it."""
    for claims in (first, second):
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _url(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ValueError(f"the discovery document has no valid {name}")
    return value
