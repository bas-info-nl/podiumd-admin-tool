"""A fake Keycloak realm behind an ``httpx2.MockTransport``, for the OIDC adapter tests.

It serves the discovery document, the JWKS and the token endpoint, and signs
tokens with its own RSA key, so the adapter's validation runs for real. A test
changes what the token endpoint answers or which claims the tokens carry.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx2
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://keycloak.onsdorp.example/realms/podiumd"
CLIENT_ID = "podiumd-admin"
CLIENT_SECRET = "client-secret-value"  # noqa: S105 - a test value, not a secret
SUBJECT = "f3b2c1d0-0000-4000-8000-000000000001"
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"


def _now() -> int:
    return int(time.time())


@dataclass
class FakeKeycloak:
    """One realm: discovery, JWKS and token endpoint."""

    key: RSAKey = field(default_factory=lambda: RSAKey.generate_key(2048, {"kid": "key-1"}))
    available: bool = True
    token_status: int = 200
    token_error: str | None = None
    nonce: str | None = None
    roles: list[str] = field(default_factory=lambda: ["viewer"])
    id_token_claims: dict[str, Any] = field(default_factory=dict)
    access_token_claims: dict[str, Any] = field(default_factory=dict)
    include_id_token: bool = True
    requests: list[httpx2.Request] = field(default_factory=list)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def sign(self, claims: dict[str, Any], *, key: RSAKey | None = None, **header: Any) -> str:
        signing_key = key if key is not None else self.key
        return jwt.encode({"alg": "RS256", "kid": signing_key.kid, **header}, claims, signing_key)

    def id_token(self, **overrides: Any) -> str:
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "sub": SUBJECT,
            "iat": _now(),
            "exp": _now() + 300,
            "sid": "kc-sid-1",
            "preferred_username": "j.jansen",
        }
        if self.nonce is not None:
            claims["nonce"] = self.nonce
        claims.update(self.id_token_claims)
        claims.update(overrides)
        return self.sign({key: value for key, value in claims.items() if value is not None})

    def access_token(self, **overrides: Any) -> str:
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": "account",
            "azp": CLIENT_ID,
            "sub": SUBJECT,
            "iat": _now(),
            "exp": _now() + 300,
            "sid": "kc-sid-1",
            "preferred_username": "j.jansen",
            "resource_access": {CLIENT_ID: {"roles": self.roles}},
        }
        claims.update(self.access_token_claims)
        claims.update(overrides)
        return self.sign({key: value for key, value in claims.items() if value is not None})

    def logout_token(self, **overrides: Any) -> str:
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": _now(),
            "exp": _now() + 120,
            "jti": "logout-1",
            "sub": SUBJECT,
            "sid": "kc-sid-1",
            "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
        }
        claims.update(overrides)
        return self.sign(
            {key: value for key, value in claims.items() if value is not None}, typ="logout+jwt"
        )

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if not self.available:
            raise httpx2.ConnectError("Keycloak cannot be reached", request=request)
        path = request.url.path
        if path == "/realms/podiumd/.well-known/openid-configuration":
            return httpx2.Response(200, json=self.discovery())
        if path == "/realms/podiumd/protocol/openid-connect/certs":
            return httpx2.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/realms/podiumd/protocol/openid-connect/token":
            return self._token(request)
        return httpx2.Response(404)

    def discovery(self) -> dict[str, Any]:
        base = f"{ISSUER}/protocol/openid-connect"
        return {
            "issuer": ISSUER,
            "authorization_endpoint": f"{base}/auth",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/certs",
            "end_session_endpoint": f"{base}/logout",
        }

    def form(self, request: httpx2.Request) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        if self.token_error is not None:
            return httpx2.Response(
                self.token_status,
                json={"error": self.token_error, "error_description": "<b>free text</b>"},
            )
        if self.token_status != 200:
            return httpx2.Response(self.token_status, text="gateway error")
        body: dict[str, Any] = {
            "access_token": self.access_token(),
            "expires_in": 300,
            "refresh_token": "refresh-token-value",
            "token_type": "Bearer",
        }
        if self.include_id_token:
            body["id_token"] = self.id_token()
        return httpx2.Response(
            200, content=json.dumps(body).encode(), headers={"content-type": "application/json"}
        )
