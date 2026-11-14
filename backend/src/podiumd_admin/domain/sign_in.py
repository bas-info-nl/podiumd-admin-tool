"""A sign-in attempt: what the server remembers between sign-in start and callback.

Spec: authentication, "Safe return after sign-in and sign-out". Design D2:

- a pre-auth record holds ``state``, ``nonce``, the PKCE verifier and the
  validated return path; it is bound to the browser that started the attempt
  and used once;
- the return path is accepted only as a relative path within the Admin Tool
  Instance, starting with a single ``/``; any other value becomes ``/``.

The random values are never shown in a ``repr``, so they cannot end up in a log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

SIGN_IN_ATTEMPT_LIFETIME: Final = timedelta(minutes=10)
"""How long a user may take at Keycloak before the callback is refused."""

MAX_RETURN_PATH_LENGTH: Final = 2000
MAX_RANDOM_VALUE_LENGTH: Final = 255
START_PAGE: Final = "/"

# RFC 7636, section 4.1: 43 to 128 unreserved characters.
_CODE_VERIFIER: Final = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
# Printable ASCII without space and backslash. Browsers read ``/\host`` as
# ``//host``, and control characters can split or hide a URL.
_SAFE_PATH: Final = re.compile(r"/(?![/\\])[!-\[\]-~]*")


class InvalidSignInAttemptError(ValueError):
    """A sign-in attempt was built with a missing or invalid value. Never includes the value."""


def safe_return_path(value: str | None) -> str:
    """``value`` if it is a relative path starting with a single ``/``; else ``/``."""
    if value is None or len(value) > MAX_RETURN_PATH_LENGTH:
        return START_PAGE
    if _SAFE_PATH.fullmatch(value) is None:
        return START_PAGE
    return value


def _random_value(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_RANDOM_VALUE_LENGTH:
        raise InvalidSignInAttemptError(f"{name} must be non-blank text")


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInAttempt:
    """One sign-in in progress, from the redirect to Keycloak until the callback."""

    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    return_path: str
    created_at: datetime

    def __post_init__(self) -> None:
        _random_value("state", self.state)
        _random_value("nonce", self.nonce)
        if not isinstance(self.code_verifier, str) or not _CODE_VERIFIER.fullmatch(
            self.code_verifier
        ):
            raise InvalidSignInAttemptError(
                "code_verifier must be 43 to 128 unreserved characters (RFC 7636)"
            )
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise InvalidSignInAttemptError("created_at must be a timezone-aware datetime")
        # Normalise in place; object.__setattr__ is the documented way to do
        # this in a frozen dataclass.
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        object.__setattr__(self, "return_path", safe_return_path(self.return_path))

    @property
    def expires_at(self) -> datetime:
        """When the callback for this attempt is no longer accepted."""
        return self.created_at + SIGN_IN_ATTEMPT_LIFETIME

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at
