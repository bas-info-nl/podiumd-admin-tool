"""Audit Entries: one record in the Audit Log.

Spec: audit-log, "What is recorded". Design D4:

- the outcome is one of ``allowed|denied|succeeded|failed|info``;
- reason codes come from the fixed ``ReasonCode`` enum, so free text from
  requests or a Keycloak ``error_description`` is never stored;
- every text field is truncated to a fixed limit;
- parameters never hold secret values: secret-like parameter names are
  rejected, because a value cannot reliably be recognised as a secret.

``ReasonCode`` is the single source of reason codes. The authorisation policy
returns its ``no-role`` and ``missing-permission`` members as denial reasons.
"""

from __future__ import annotations

import ipaddress
import itertools
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from podiumd_admin.domain.environment import EnvironmentIdentity


class Outcome(StrEnum):
    """The outcome of what an Audit Entry records."""

    ALLOWED = "allowed"
    """An attempt was allowed; for an action it is recorded before it takes effect."""
    DENIED = "denied"
    """An attempt was refused."""
    SUCCEEDED = "succeeded"
    """An action whose effect completes later succeeded (from change 2 onwards)."""
    FAILED = "failed"
    """An action whose effect completes later failed (from change 2 onwards)."""
    INFO = "info"
    """A system event, such as a session expiry."""


class ReasonCode(StrEnum):
    """Why something was denied or happened. A fixed set: never free text."""

    # Denials of an authenticated user.
    NO_ROLE = "no-role"
    MISSING_PERMISSION = "missing-permission"
    CSRF = "csrf"

    # Session expiries, recorded with outcome ``info``.
    IDLE = "idle"
    MAX_LIFETIME = "max-lifetime"
    REFRESH_REFUSED = "refresh-refused"
    BACKCHANNEL_LOGOUT = "backchannel-logout"

    # Failures without an authenticated user. They go to stdout only, through
    # the unauthenticated-failure aggregator, and never become Audit Entries.
    INVALID_STATE = "invalid-state"
    """A sign-in callback whose ``state`` does not match or has expired."""
    CALLBACK_ERROR = "callback-error"
    """A sign-in callback carrying an error response from Keycloak."""
    TOKEN_EXCHANGE_FAILED = "token-exchange-failed"  # noqa: S105 - a reason code, not a password
    """Exchanging the authorisation code for tokens failed."""
    NO_SESSION = "no-session"
    """A request without a valid session."""


DENIAL_REASONS: Final = frozenset(
    {ReasonCode.NO_ROLE, ReasonCode.MISSING_PERMISSION, ReasonCode.CSRF}
)
SESSION_EXPIRY_REASONS: Final = frozenset(
    {
        ReasonCode.IDLE,
        ReasonCode.MAX_LIFETIME,
        ReasonCode.REFRESH_REFUSED,
        ReasonCode.BACKCHANNEL_LOGOUT,
    }
)
UNAUTHENTICATED_REASONS: Final = frozenset(
    {
        ReasonCode.INVALID_STATE,
        ReasonCode.CALLBACK_ERROR,
        ReasonCode.TOKEN_EXCHANGE_FAILED,
        ReasonCode.NO_SESSION,
    }
)

# Text-length limits. Longer values are truncated, ending in TRUNCATION_MARK.
MAX_ACTION_LENGTH: Final = 100
MAX_TARGET_LENGTH: Final = 500
MAX_USER_SUBJECT_LENGTH: Final = 255
MAX_USERNAME_LENGTH: Final = 255
MAX_CORRELATION_ID_LENGTH: Final = 100
MAX_PARAMETER_KEY_LENGTH: Final = 64
MAX_PARAMETER_VALUE_LENGTH: Final = 500
MAX_PARAMETERS: Final = 32
TRUNCATION_MARK: Final = "…"

type ParameterValue = str | int | bool | None
"""A parameter value: plain values only, so nothing structured hides a secret."""


class InvalidAuditEntryError(ValueError):
    """An Audit Entry was built with a missing or invalid value."""


class SecretParameterError(InvalidAuditEntryError):
    """A parameter name looks like it holds a secret. The value is never included."""

    def __init__(self, key: str) -> None:
        super().__init__(f"parameter {key!r} looks like a secret and must not be recorded")
        self.key = key


# Words in a parameter name that mark it as secret-like. Names are split into
# words on separators and camelCase, so ``clientSecret``, ``api_key`` and
# ``refresh-token`` are caught while ``monkey`` and ``author`` are not.
_SECRET_WORDS: Final = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "secret",
        "token",
        "key",
        "apikey",
        "privatekey",
        "credential",
        "credentials",
        "authorization",
        "auth",
        "cookie",
        "sessionid",
    }
)
# Words that also mark a name when glued to another word, as in ``accesstoken``.
_SECRET_SUFFIXES: Final = ("password", "passwd", "passphrase", "secret", "token")
_WORD_BOUNDARY: Final = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def is_secret_like(name: str) -> bool:
    """Whether a parameter name looks like it holds a secret value."""
    words = [word.lower() for word in _WORD_BOUNDARY.split(name) if word]
    pairs = (first + second for first, second in itertools.pairwise(words))
    return any(
        word in _SECRET_WORDS or word.endswith(_SECRET_SUFFIXES) for word in [*words, *pairs]
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - len(TRUNCATION_MARK)] + TRUNCATION_MARK


def _required_text(name: str, value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAuditEntryError(f"{name} is required")
    return _truncate(value.strip(), limit)


def _optional_text(name: str, value: object, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidAuditEntryError(f"{name} must be text when given")
    return _truncate(value.strip(), limit) or None


def normalise_client_ip(value: object) -> str:
    """Return a client IP address in its normalised text form.

    Raises ``ValueError`` for anything that is not a single IPv4 or IPv6
    address, so no free text ends up where a client IP belongs.
    """
    if not isinstance(value, str):
        raise ValueError("client_ip must be an IP address in text form")
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        raise ValueError(f"client_ip must be an IP address, got {value!r}") from None


def _client_ip(value: object) -> str | None:
    if value is None:
        return None
    try:
        return normalise_client_ip(value)
    except ValueError as error:
        raise InvalidAuditEntryError(str(error)) from None


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidAuditEntryError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _parameters(value: object) -> Mapping[str, ParameterValue]:
    if not isinstance(value, Mapping):
        raise InvalidAuditEntryError("parameters must be a mapping of names to values")
    if len(value) > MAX_PARAMETERS:
        raise InvalidAuditEntryError(f"parameters hold at most {MAX_PARAMETERS} values")

    result: dict[str, ParameterValue] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise InvalidAuditEntryError("every parameter needs a non-blank name")
        if is_secret_like(key):
            raise SecretParameterError(key)
        # bool is an int subclass and is allowed; float, bytes and containers are not.
        if item is not None and not isinstance(item, str | int):
            raise InvalidAuditEntryError(
                f"parameter {key!r} must be text, a whole number, a boolean or None"
            )
        name = _truncate(key.strip(), MAX_PARAMETER_KEY_LENGTH)
        # Truncation can turn a harmless name into a secret-like one, such as
        # ``..._tokenizer_name`` into ``..._token…``. Reject it here, so every
        # accepted entry is accepted again when it is read back.
        if is_secret_like(name):
            raise SecretParameterError(key)
        if name in result:
            raise InvalidAuditEntryError(f"parameter names collide after truncation: {name!r}")
        result[name] = (
            _truncate(item, MAX_PARAMETER_VALUE_LENGTH) if isinstance(item, str) else item
        )
    return MappingProxyType(result)


def _empty_parameters() -> Mapping[str, ParameterValue]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    """One record in the Audit Log: who did or attempted what, when and where.

    Values are validated and normalised when the entry is built: text is
    trimmed and truncated, the timestamp is converted to UTC, the client IP is
    normalised and parameters are copied into a read-only mapping.

    ``reason`` is required for ``denied`` and ``info`` entries and absent for
    ``allowed`` and ``succeeded`` ones. ``user_subject`` and ``username`` are
    the Keycloak subject and username, when known. ``client_ip`` is absent only
    for system events that no request caused, such as an expiry found by the
    sweep.
    """

    occurred_at: datetime
    environment: EnvironmentIdentity
    action: str
    outcome: Outcome
    correlation_id: str
    reason: ReasonCode | None = None
    user_subject: str | None = None
    username: str | None = None
    target: str | None = None
    parameters: Mapping[str, ParameterValue] = field(default_factory=_empty_parameters)
    client_ip: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.id, uuid.UUID):
            raise InvalidAuditEntryError("id must be a UUID")
        if not isinstance(self.environment, EnvironmentIdentity):
            raise InvalidAuditEntryError("environment must be an EnvironmentIdentity")
        if not isinstance(self.outcome, Outcome):
            raise InvalidAuditEntryError(f"outcome must be an Outcome, got {self.outcome!r}")
        self._check_reason()

        # Normalise in place; object.__setattr__ is the documented way to do
        # this in a frozen dataclass.
        normalised: dict[str, object] = {
            "occurred_at": _utc("occurred_at", self.occurred_at),
            "action": _required_text("action", self.action, MAX_ACTION_LENGTH),
            "correlation_id": _required_text(
                "correlation_id", self.correlation_id, MAX_CORRELATION_ID_LENGTH
            ),
            "user_subject": _optional_text(
                "user_subject", self.user_subject, MAX_USER_SUBJECT_LENGTH
            ),
            "username": _optional_text("username", self.username, MAX_USERNAME_LENGTH),
            "target": _optional_text("target", self.target, MAX_TARGET_LENGTH),
            "parameters": _parameters(self.parameters),
            "client_ip": _client_ip(self.client_ip),
        }
        for name, value in normalised.items():
            object.__setattr__(self, name, value)

    def _check_reason(self) -> None:
        if self.reason is not None and not isinstance(self.reason, ReasonCode):
            raise InvalidAuditEntryError(f"reason must be a ReasonCode, got {self.reason!r}")
        if self.reason in UNAUTHENTICATED_REASONS:
            raise InvalidAuditEntryError(
                f"reason {self.reason} is for unauthenticated failures, "
                "which are written to stdout and never stored as Audit Entries"
            )
        if self.outcome in (Outcome.DENIED, Outcome.INFO) and self.reason is None:
            raise InvalidAuditEntryError(f"a reason is required for outcome {self.outcome}")
        if self.outcome in (Outcome.ALLOWED, Outcome.SUCCEEDED) and self.reason is not None:
            raise InvalidAuditEntryError(f"outcome {self.outcome} carries no reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class UnauthenticatedFailureSummary:
    """Identical unauthenticated failures from one client, combined into one stdout line.

    Spec: audit-log, "Recording unauthenticated failures". ``client_ip`` is
    ``None`` for the overflow line that combines clients the aggregator had no
    room left to track separately.
    """

    client_ip: str | None
    reason: ReasonCode
    count: int
    first_at: datetime
    last_at: datetime

    def __post_init__(self) -> None:
        if self.reason not in UNAUTHENTICATED_REASONS:
            raise ValueError(f"reason {self.reason!r} is not an unauthenticated-failure reason")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError(f"count must be at least 1, got {self.count!r}")
        if self.last_at - self.first_at < timedelta(0):
            raise ValueError("last_at must not be before first_at")
