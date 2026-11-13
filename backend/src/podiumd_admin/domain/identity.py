"""What Keycloak vouches for about a user, after the identity provider validated it.

Design D2 and D3. The OIDC adapter validates the tokens (signature, issuer,
audience, expiry, nonce) and hands the application a ``VerifiedIdentity``:
the user's identity, the claims the roles are read from, and the tokens the
session keeps server-side. The application never parses a token itself, so it
does not depend on any OIDC library (ADR 0009).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from podiumd_admin.domain.session import SessionTokens


def _empty_claims() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedIdentity:
    """A user as Keycloak vouches for them after a code exchange or a token refresh.

    ``claims`` are the validated access-token claims, which hold the client
    roles (design D3). ``keycloak_session_id`` is the ``sid`` claim.
    """

    subject: str
    username: str | None
    keycloak_session_id: str | None
    tokens: SessionTokens
    claims: Mapping[str, object] = field(default_factory=_empty_claims, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("subject is required")
        if not isinstance(self.tokens, SessionTokens):
            raise ValueError("tokens must be SessionTokens")
        object.__setattr__(self, "claims", MappingProxyType(dict(self.claims)))


@dataclass(frozen=True, slots=True)
class LogoutNotice:
    """A validated back-channel logout: Keycloak ended the session with this ``sid``."""

    keycloak_session_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.keycloak_session_id, str) or not self.keycloak_session_id.strip():
            raise ValueError("keycloak_session_id is required")
