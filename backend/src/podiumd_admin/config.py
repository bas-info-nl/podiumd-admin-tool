"""The configuration an Admin Tool Instance starts with (design D1, D2, D5, D8).

Spec: installation, "Installed with a Helm chart, configured only through
values", "Session encryption keys" and "Trusted proxies"; environment-context,
"Environment identity is configured at installation".

The Helm chart passes every value as a ``PODIUMD_ADMIN_*`` environment
variable. pydantic-settings reads them as text; ``load_settings`` then
validates every value, builds the domain objects (``EnvironmentIdentity``,
``RoleMapping``, ``SessionTimeouts``) and reports every problem at once in one
``ConfigurationError``, each under the name of the environment variable it came
from. Error messages never echo a secret value.

The two database URLs are separate settings, because the two database roles
are used by different processes (design D4, D8):

- ``PODIUMD_ADMIN_DATABASE_APP_URL``: the app role, used by the running
  Admin Tool Instance; part of ``Settings``;
- ``PODIUMD_ADMIN_DATABASE_OWNER_URL``: the owner role, used only by the
  migration Job (``alembic upgrade head``); read by
  ``load_owner_database_url`` and never part of ``Settings``, so the running
  instance does not hold the owner credentials.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from podiumd_admin.domain.client_ip import IPNetwork
from podiumd_admin.domain.environment import (
    EnvironmentIdentity,
    IdentityField,
    InvalidEnvironmentIdentityError,
)
from podiumd_admin.domain.roles import (
    DEFAULT_OPERATOR_ROLE_NAME,
    DEFAULT_VIEWER_ROLE_NAME,
    InvalidRoleMappingError,
    RoleMapping,
)
from podiumd_admin.domain.session_timeouts import (
    DEFAULT_ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT,
    InvalidSessionTimeoutsError,
    SessionTimeouts,
    TimeoutField,
)

PREFIX: Final = "PODIUMD_ADMIN_"

ENVIRONMENT_MUNICIPALITY: Final = f"{PREFIX}ENVIRONMENT_MUNICIPALITY"
ENVIRONMENT_STAGE: Final = f"{PREFIX}ENVIRONMENT_STAGE"
ENVIRONMENT_LABEL: Final = f"{PREFIX}ENVIRONMENT_LABEL"
PUBLIC_HOSTNAME: Final = f"{PREFIX}PUBLIC_HOSTNAME"
OIDC_ISSUER: Final = f"{PREFIX}OIDC_ISSUER"
OIDC_CLIENT_ID: Final = f"{PREFIX}OIDC_CLIENT_ID"
OIDC_CLIENT_SECRET: Final = f"{PREFIX}OIDC_CLIENT_SECRET"
AUTH_ROLE_CLAIM: Final = f"{PREFIX}AUTH_ROLE_CLAIM"
AUTH_ROLES_VIEWER: Final = f"{PREFIX}AUTH_ROLES_VIEWER"
AUTH_ROLES_OPERATOR: Final = f"{PREFIX}AUTH_ROLES_OPERATOR"
DATABASE_APP_URL: Final = f"{PREFIX}DATABASE_APP_URL"
DATABASE_OWNER_URL: Final = f"{PREFIX}DATABASE_OWNER_URL"
SESSION_ENCRYPTION_KEYS: Final = f"{PREFIX}SESSION_ENCRYPTION_KEYS"
SESSION_IDLE_TIMEOUT_MINUTES: Final = f"{PREFIX}SESSION_IDLE_TIMEOUT_MINUTES"
SESSION_MAX_LIFETIME_MINUTES: Final = f"{PREFIX}SESSION_MAX_LIFETIME_MINUTES"
TRUSTED_PROXIES: Final = f"{PREFIX}TRUSTED_PROXIES"

_IDENTITY_SETTINGS: Final[dict[IdentityField, str]] = {
    "municipality": ENVIRONMENT_MUNICIPALITY,
    "stage": ENVIRONMENT_STAGE,
    "label": ENVIRONMENT_LABEL,
}
_TIMEOUT_SETTINGS: Final[dict[TimeoutField, str]] = {
    "idle_timeout": SESSION_IDLE_TIMEOUT_MINUTES,
    "absolute_lifetime": SESSION_MAX_LIFETIME_MINUTES,
}

# The session encryption key shipped for local development (task 12.2). It is
# public, so an instance refuses to start with it unless its public hostname is
# a loopback name, which no Environment can use. It is built from readable
# bytes, so it is obviously not a real secret; the ``?`` characters make its
# url-safe and standard base64 spellings differ, which the tests rely on.
DEVELOPMENT_SESSION_ENCRYPTION_KEY: Final = base64.urlsafe_b64encode(
    b"podiumd-admin-dev-key-only?????!"
).decode()

_REQUIRED: Final = "is required"
_HOSTNAME: Final = re.compile(
    r"(?P<host>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)"
    r"(?::(?P<port>[0-9]{1,5}))?"
)
_MAX_HOSTNAME_LENGTH: Final = 253
_DATABASE_DRIVER: Final = "postgresql+psycopg"
_PLAIN_DATABASE_DRIVER: Final = "postgresql"


@dataclass(frozen=True, slots=True)
class ConfigurationProblem:
    """One invalid or missing setting, named by its environment variable."""

    setting: str
    message: str


class ConfigurationError(Exception):
    """The configuration is incomplete or invalid, so the instance must not start."""

    def __init__(self, problems: Iterable[ConfigurationProblem]) -> None:
        self.problems: tuple[ConfigurationProblem, ...] = tuple(problems)
        details = "; ".join(f"{problem.setting} {problem.message}" for problem in self.problems)
        super().__init__(f"invalid configuration: {details}")


@dataclass(frozen=True, slots=True)
class Settings:
    """The validated configuration of an Admin Tool Instance.

    Secret values are ``SecretStr``, so they never show in a ``repr`` or a log.
    """

    environment: EnvironmentIdentity
    public_hostname: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: SecretStr
    role_mapping: RoleMapping
    database_app_url: SecretStr
    session_encryption_keys: tuple[SecretStr, ...]
    session_timeouts: SessionTimeouts
    trusted_proxies: tuple[IPNetwork, ...]


class _Source(BaseSettings):
    """The raw ``PODIUMD_ADMIN_*`` values, as text; ``None`` when not set."""

    model_config = SettingsConfigDict(env_prefix=PREFIX, case_sensitive=True, extra="ignore")

    ENVIRONMENT_MUNICIPALITY: str | None = None
    ENVIRONMENT_STAGE: str | None = None
    ENVIRONMENT_LABEL: str | None = None
    PUBLIC_HOSTNAME: str | None = None
    OIDC_ISSUER: str | None = None
    OIDC_CLIENT_ID: str | None = None
    OIDC_CLIENT_SECRET: SecretStr | None = None
    AUTH_ROLE_CLAIM: str | None = None
    AUTH_ROLES_VIEWER: str | None = None
    AUTH_ROLES_OPERATOR: str | None = None
    DATABASE_APP_URL: SecretStr | None = None
    SESSION_ENCRYPTION_KEYS: SecretStr | None = None
    SESSION_IDLE_TIMEOUT_MINUTES: str | None = None
    SESSION_MAX_LIFETIME_MINUTES: str | None = None
    TRUSTED_PROXIES: str | None = None


class _OwnerSource(BaseSettings):
    """The owner-role database URL, read only by the migrations."""

    model_config = SettingsConfigDict(env_prefix=PREFIX, case_sensitive=True, extra="ignore")

    DATABASE_OWNER_URL: SecretStr | None = None


class _Problems:
    """Collects problems, so every invalid setting is reported at once."""

    def __init__(self) -> None:
        self.found: list[ConfigurationProblem] = []

    def add(self, setting: str, message: str) -> None:
        self.found.append(ConfigurationProblem(setting, message))

    def required(self, setting: str, value: str | SecretStr | None) -> str | None:
        """The trimmed value, or ``None`` after reporting it as missing."""
        text = _text(value)
        if not text:
            self.add(setting, _REQUIRED)
            return None
        return text


def _text(value: str | SecretStr | None) -> str:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return value.strip() if value is not None else ""


def load_settings() -> Settings:
    """Read and validate the configuration from the process environment.

    Raises ``ConfigurationError`` naming every missing or invalid setting.
    """
    source = _Source()
    problems = _Problems()

    municipality = problems.required(ENVIRONMENT_MUNICIPALITY, source.ENVIRONMENT_MUNICIPALITY)
    stage = problems.required(ENVIRONMENT_STAGE, source.ENVIRONMENT_STAGE)
    hostname_value = problems.required(PUBLIC_HOSTNAME, source.PUBLIC_HOSTNAME)
    issuer_value = problems.required(OIDC_ISSUER, source.OIDC_ISSUER)
    client_id = problems.required(OIDC_CLIENT_ID, source.OIDC_CLIENT_ID)
    client_secret = problems.required(OIDC_CLIENT_SECRET, source.OIDC_CLIENT_SECRET)
    app_url_value = problems.required(DATABASE_APP_URL, source.DATABASE_APP_URL)

    environment = None
    if municipality is not None and stage is not None:
        environment = _environment(problems, municipality, stage, source.ENVIRONMENT_LABEL)
    public_hostname = _checked(problems, PUBLIC_HOSTNAME, hostname_value, _public_hostname)
    oidc_issuer = _checked(problems, OIDC_ISSUER, issuer_value, _issuer)
    role_mapping = _role_mapping(problems, source, client_id)
    app_url = _checked(problems, DATABASE_APP_URL, app_url_value, _database_url)
    keys = _encryption_keys(problems, source.SESSION_ENCRYPTION_KEYS, public_hostname)
    timeouts = _session_timeouts(problems, source)
    trusted_proxies = _checked(problems, TRUSTED_PROXIES, source.TRUSTED_PROXIES, _proxies)

    if problems.found:
        raise ConfigurationError(problems.found)
    # Every value is present once no problem was found; the asserts tell mypy.
    assert environment is not None  # noqa: S101
    assert public_hostname is not None  # noqa: S101
    assert oidc_issuer is not None  # noqa: S101
    assert client_id is not None  # noqa: S101
    assert client_secret is not None  # noqa: S101
    assert role_mapping is not None  # noqa: S101
    assert app_url is not None  # noqa: S101
    assert keys is not None  # noqa: S101
    assert timeouts is not None  # noqa: S101
    return Settings(
        environment=environment,
        public_hostname=public_hostname,
        oidc_issuer=oidc_issuer,
        oidc_client_id=client_id,
        oidc_client_secret=SecretStr(client_secret),
        role_mapping=role_mapping,
        database_app_url=SecretStr(app_url),
        session_encryption_keys=keys,
        session_timeouts=timeouts,
        trusted_proxies=trusted_proxies or (),
    )


def load_owner_database_url() -> str:
    """The owner-role database URL for the migrations, from ``DATABASE_OWNER_URL``.

    Raises ``ConfigurationError`` naming the setting when it is missing or invalid.
    """
    problems = _Problems()
    value = problems.required(DATABASE_OWNER_URL, _OwnerSource().DATABASE_OWNER_URL)
    url = _checked(problems, DATABASE_OWNER_URL, value, _database_url)
    if problems.found or url is None:
        raise ConfigurationError(problems.found)
    return url


def _checked[T](
    problems: _Problems, setting: str, value: str | None, parse: Callable[[str], T]
) -> T | None:
    """``parse(value)``, or ``None`` after reporting its ``ValueError`` under ``setting``.

    A missing value (``None``) has been reported already, or is optional.
    """
    if value is None:
        return None
    try:
        return parse(value)
    except ValueError as error:
        problems.add(setting, str(error))
        return None


def _environment(
    problems: _Problems, municipality: str, stage: str, label: str | None
) -> EnvironmentIdentity | None:
    try:
        return EnvironmentIdentity.from_config(
            municipality=municipality, stage=stage.strip(), label=label
        )
    except InvalidEnvironmentIdentityError as error:
        problems.add(_IDENTITY_SETTINGS[error.field], error.problem)
        return None


def _public_hostname(value: str) -> str:
    """A bare hostname with an optional port, in lower case."""
    hostname = value.strip().lower()
    match = _HOSTNAME.fullmatch(hostname)
    if (
        match is None
        or len(match["host"]) > _MAX_HOSTNAME_LENGTH
        or (match["port"] is not None and not 1 <= int(match["port"]) <= 65535)
    ):
        # The value is not echoed: a mistyped value may hold credentials.
        raise ValueError(
            "must be a bare hostname with an optional port, such as admin.example.nl or "
            "admin.example.nl:8443, without a scheme, path or user"
        )
    return hostname


def _is_loopback_host(host: str) -> bool:
    """Whether a bare host (no port, no brackets) is a loopback name or address.

    Used only to allow local development settings.
    """
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_local_public_hostname(public_hostname: str | None) -> bool:
    """Whether a validated public hostname (an optional port, never an IPv6 literal) is local."""
    if public_hostname is None:
        return False
    match = _HOSTNAME.fullmatch(public_hostname)
    return match is not None and _is_loopback_host(match["host"])


def _issuer(value: str) -> str:
    """An https URL without query, fragment or user; http only for a local Keycloak."""
    issuer = value.strip()
    problem = "must be the https URL of the Keycloak realm, without user, query or fragment"
    try:
        parts = urlsplit(issuer)
        hostname = parts.hostname
        _ = parts.port  # raises ValueError for an invalid port
    except ValueError:
        raise ValueError(problem) from None
    # ``urlsplit`` already removed the port and the IPv6 brackets.
    local = parts.scheme == "http" and hostname is not None and _is_loopback_host(hostname)
    if (
        (parts.scheme != "https" and not local)
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or "?" in issuer
        or "#" in issuer
    ):
        raise ValueError(problem)
    return issuer


def _database_url(value: str) -> str:
    """A PostgreSQL URL for the psycopg driver; a plain ``postgresql://`` URL gets it."""
    problem = (
        f"must be a database URL such as {_DATABASE_DRIVER}://user:password@host:5432/database"
    )
    try:
        url = make_url(value.strip())
    except (ArgumentError, ValueError):
        # Not chained: the parser's message may hold the value.
        raise ValueError(problem) from None
    if url.drivername == _PLAIN_DATABASE_DRIVER:
        url = url.set(drivername=_DATABASE_DRIVER)
    if url.drivername != _DATABASE_DRIVER or not url.database:
        raise ValueError(problem)
    return url.render_as_string(hide_password=False)


def _role_mapping(
    problems: _Problems, source: _Source, client_id: str | None
) -> RoleMapping | None:
    claim_path: tuple[str, ...] | None = None
    if source.AUTH_ROLE_CLAIM is not None:
        claim_path = _checked(problems, AUTH_ROLE_CLAIM, source.AUTH_ROLE_CLAIM, _claim_path)
        if claim_path is None:
            return None
    elif client_id is None:
        # The default claim path needs the client id, which was reported missing.
        return None

    viewer = _role_name(
        problems, AUTH_ROLES_VIEWER, source.AUTH_ROLES_VIEWER, DEFAULT_VIEWER_ROLE_NAME
    )
    operator = _role_name(
        problems, AUTH_ROLES_OPERATOR, source.AUTH_ROLES_OPERATOR, DEFAULT_OPERATOR_ROLE_NAME
    )
    if not viewer or not operator:
        return None
    if viewer == operator:
        problems.add(f"{AUTH_ROLES_VIEWER}, {AUTH_ROLES_OPERATOR}", "must name different roles")
        return None

    try:
        if claim_path is None:
            assert client_id is not None  # noqa: S101 - checked above
            return RoleMapping.for_client(
                client_id, viewer_role_name=viewer, operator_role_name=operator
            )
        return RoleMapping(
            claim_path=claim_path, viewer_role_name=viewer, operator_role_name=operator
        )
    except InvalidRoleMappingError as error:  # pragma: no cover - every case is checked above
        problems.add(f"{AUTH_ROLE_CLAIM}, {AUTH_ROLES_VIEWER}, {AUTH_ROLES_OPERATOR}", str(error))
        return None


def _role_name(problems: _Problems, setting: str, value: str | None, default: str) -> str:
    """The configured role name, the default when unset, or ``""`` after reporting it."""
    name = default if value is None else value.strip()
    if not name:
        problems.add(setting, "must be a role name when set")
    return name


def _claim_path(value: str) -> tuple[str, ...]:
    """A dot-separated claim path, such as ``resource_access.podiumd-admin.roles``."""
    segments = tuple(segment.strip() for segment in value.strip().split("."))
    if not all(segments):
        raise ValueError(
            "must be a dot-separated claim path, such as resource_access.podiumd-admin.roles"
        )
    return segments


def _key_bytes(key: str) -> bytes | None:
    """The bytes of a Fernet key, decoded the way ``Fernet`` decodes them."""
    try:
        Fernet(key)
        return base64.urlsafe_b64decode(key)
    except (ValueError, binascii.Error):
        return None


_DEVELOPMENT_KEY_BYTES: Final = base64.urlsafe_b64decode(DEVELOPMENT_SESSION_ENCRYPTION_KEY)


def _encryption_keys(
    problems: _Problems, value: SecretStr | None, public_hostname: str | None
) -> tuple[SecretStr, ...] | None:
    """The primary key first, then older keys; comma-separated.

    Problems name a key by its position, never by its value.
    """
    keys = [key.strip() for key in _text(value).split(",") if key.strip()]
    if not keys:
        problems.add(SESSION_ENCRYPTION_KEYS, _REQUIRED)
        return None
    local = _is_local_public_hostname(public_hostname)
    found: list[str] = []
    for position, key in enumerate(keys, start=1):
        key_bytes = _key_bytes(key)
        if key_bytes is None:
            found.append(
                f"key {position} is not a valid Fernet key (32 url-safe base64-encoded bytes)"
            )
        elif key_bytes == _DEVELOPMENT_KEY_BYTES and not local:
            found.append(
                f"key {position} is the known development key, which is only accepted "
                "for a localhost public hostname; generate a new key"
            )
    if found:
        problems.add(SESSION_ENCRYPTION_KEYS, "; ".join(found))
        return None
    return tuple(SecretStr(key) for key in keys)


def _minutes(value: str) -> timedelta:
    try:
        minutes = int(value.strip())
    except ValueError:
        raise ValueError("must be an integer number of minutes") from None
    try:
        return timedelta(minutes=minutes)
    except OverflowError:
        # Reported as a ValueError, so ``_checked`` names the setting.
        raise ValueError("is too large for a number of minutes") from None


def _session_timeouts(problems: _Problems, source: _Source) -> SessionTimeouts | None:
    before = len(problems.found)
    idle = _checked(
        problems, SESSION_IDLE_TIMEOUT_MINUTES, source.SESSION_IDLE_TIMEOUT_MINUTES, _minutes
    )
    lifetime = _checked(
        problems, SESSION_MAX_LIFETIME_MINUTES, source.SESSION_MAX_LIFETIME_MINUTES, _minutes
    )
    if len(problems.found) > before:
        return None
    try:
        return SessionTimeouts(
            idle_timeout=idle if idle is not None else DEFAULT_IDLE_TIMEOUT,
            absolute_lifetime=lifetime if lifetime is not None else DEFAULT_ABSOLUTE_LIFETIME,
        )
    except InvalidSessionTimeoutsError as error:
        problems.add(_TIMEOUT_SETTINGS[error.field], error.problem)
        return None


def _proxies(value: str) -> tuple[IPNetwork, ...]:
    """Comma-separated addresses or CIDR ranges; blank trusts no proxy."""
    networks: list[IPNetwork] = []
    for entry in (entry.strip() for entry in value.split(",")):
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry)
        except ValueError:
            raise ValueError(
                f"must be IP addresses or CIDR ranges such as 10.0.0.0/8, got {entry!r}"
            ) from None
        if network.prefixlen == 0:
            raise ValueError(
                f"must not trust every address ({entry}): any client could then choose "
                "the client IP that is recorded"
            )
        networks.append(network)
    return tuple(networks)
