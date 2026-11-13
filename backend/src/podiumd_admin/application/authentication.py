"""What the authentication use cases share: their settings and random identifiers.

Design D2. The redirect URI and the post-sign-out redirect URI are absolute
URLs built from the configured public hostname by the composition root, never
from request headers.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final

from podiumd_admin.domain.environment import EnvironmentIdentity
from podiumd_admin.domain.roles import RoleMapping
from podiumd_admin.domain.session_timeouts import SessionTimeouts

RANDOM_BYTES: Final = 32
"""Entropy of every session identifier, attempt identifier, state, nonce and verifier."""


def new_random_value() -> str:
    """A url-safe random value of ``RANDOM_BYTES`` bytes (43 characters).

    Also a valid PKCE code verifier (RFC 7636): only unreserved characters.
    """
    return secrets.token_urlsafe(RANDOM_BYTES)


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthSettings:
    """The configuration the authentication use cases run with."""

    environment: EnvironmentIdentity
    role_mapping: RoleMapping
    timeouts: SessionTimeouts
    redirect_uri: str
    """Where Keycloak sends the browser back to: ``https://<publicHostname>/auth/callback``."""
    post_logout_redirect_uri: str
    """Where Keycloak sends the browser after sign-out: the signed-out page."""
