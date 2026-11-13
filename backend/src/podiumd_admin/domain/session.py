"""Sessions: what the server keeps about a signed-in user.

Spec: authentication, "Sessions are held by the server" and "Session lifetime
and expiry". Design D2:

- all OIDC tokens stay server-side; the browser holds only an opaque session
  identifier, which is not part of a ``Session`` (the store keys sessions by
  its hash);
- ``last_seen_at`` decides the idle timeout and ``expires_at`` the absolute
  lifetime;
- ``keycloak_session_id`` is the ``sid`` claim, which back-channel logout uses
  to find the sessions to end;
- ``tokens`` is ``None`` once they have been purged, for example by the
  expiry sweep.

Identity values are rejected rather than truncated when too long, because a
shortened subject would identify someone else.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from podiumd_admin.domain.audit import MAX_USER_SUBJECT_LENGTH, MAX_USERNAME_LENGTH, ReasonCode
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session_timeouts import SessionTimeouts

MAX_KEYCLOAK_SESSION_ID_LENGTH: Final = 255
ACCESS_TOKEN_REFRESH_MARGIN: Final = timedelta(seconds=15)
"""An access token this close to its expiry is refreshed already, so it cannot expire in flight."""


class InvalidSessionError(ValueError):
    """A Session was built with a missing or invalid value. Never includes token values."""


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidSessionError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _optional_text(name: str, value: object, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSessionError(f"{name} must be text when given")
    text = value.strip()
    if len(text) > limit:
        raise InvalidSessionError(f"{name} must be at most {limit} characters")
    return text or None


def _check_token(name: str, value: object, *, required: bool) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value:
        raise InvalidSessionError(f"{name} must be non-empty text")


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionTokens:
    """The OIDC tokens of a Session. Token values never appear in ``repr``."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    id_token: str | None = field(repr=False)
    access_token_expires_at: datetime

    def __post_init__(self) -> None:
        _check_token("access_token", self.access_token, required=True)
        _check_token("refresh_token", self.refresh_token, required=False)
        _check_token("id_token", self.id_token, required=False)
        object.__setattr__(
            self,
            "access_token_expires_at",
            _utc("access_token_expires_at", self.access_token_expires_at),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """The period a user is signed in to this Admin Tool Instance."""

    user_subject: str
    username: str | None
    keycloak_session_id: str | None
    roles: frozenset[Role]
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    tokens: SessionTokens | None

    def __post_init__(self) -> None:
        user_subject = _optional_text("user_subject", self.user_subject, MAX_USER_SUBJECT_LENGTH)
        if user_subject is None:
            raise InvalidSessionError("user_subject is required")
        if not isinstance(self.roles, Set) or not all(isinstance(r, Role) for r in self.roles):
            raise InvalidSessionError("roles must be a set of Role values")
        if self.tokens is not None and not isinstance(self.tokens, SessionTokens):
            raise InvalidSessionError("tokens must be SessionTokens or None")

        created_at = _utc("created_at", self.created_at)
        last_seen_at = _utc("last_seen_at", self.last_seen_at)
        expires_at = _utc("expires_at", self.expires_at)
        if last_seen_at < created_at:
            raise InvalidSessionError("last_seen_at must not be before created_at")
        if expires_at <= created_at:
            raise InvalidSessionError("expires_at must be after created_at")

        # Normalise in place; object.__setattr__ is the documented way to do
        # this in a frozen dataclass.
        normalised: dict[str, object] = {
            "user_subject": user_subject,
            "username": _optional_text("username", self.username, MAX_USERNAME_LENGTH),
            "keycloak_session_id": _optional_text(
                "keycloak_session_id", self.keycloak_session_id, MAX_KEYCLOAK_SESSION_ID_LENGTH
            ),
            "roles": frozenset(self.roles),
            "created_at": created_at,
            "last_seen_at": last_seen_at,
            "expires_at": expires_at,
        }
        for name, value in normalised.items():
            object.__setattr__(self, name, value)


def expiry_reason(session: Session, now: datetime, timeouts: SessionTimeouts) -> ReasonCode | None:
    """Why ``session`` has ended by itself at ``now``, or ``None`` if it has not.

    The absolute lifetime (``expires_at``) is checked first, so a session past
    both limits is recorded as ``max-lifetime``.
    """
    if now >= session.expires_at:
        return ReasonCode.MAX_LIFETIME
    if now - session.last_seen_at >= timeouts.idle_timeout:
        return ReasonCode.IDLE
    return None


def access_token_expired(tokens: SessionTokens, now: datetime) -> bool:
    """Whether the access token must be refreshed before the request is authorised."""
    return now >= tokens.access_token_expires_at - ACCESS_TOKEN_REFRESH_MARGIN


def highest_role(roles: Set[Role]) -> Role | None:
    """The Role that counts for authorisation: an Operator holds every Viewer permission."""
    if Role.OPERATOR in roles:
        return Role.OPERATOR
    if Role.VIEWER in roles:
        return Role.VIEWER
    return None
