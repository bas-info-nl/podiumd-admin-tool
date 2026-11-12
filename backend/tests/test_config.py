"""The configuration an Admin Tool Instance starts with.

Spec: installation, "Installed with a Helm chart, configured only through
values", "Session encryption keys" and "Trusted proxies"; environment-context,
"Environment identity is configured at installation". The Helm chart passes
every value as a ``PODIUMD_ADMIN_*`` environment variable. Startup fails on a
missing or invalid value, with an error naming the setting, and never echoes a
secret value.
"""

from __future__ import annotations

import base64
import ipaddress
import os
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from podiumd_admin.config import (
    DATABASE_OWNER_URL,
    DEVELOPMENT_SESSION_ENCRYPTION_KEY,
    ConfigurationError,
    Settings,
    load_owner_database_url,
    load_settings,
)
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.domain.roles import RoleMapping
from podiumd_admin.domain.session_timeouts import SessionTimeouts

KEY_1 = Fernet.generate_key().decode()
KEY_2 = Fernet.generate_key().decode()
APP_URL = "postgresql+psycopg://podiumd_admin_app:app-password@db:5432/podiumd_admin"
OWNER_URL = "postgresql+psycopg://podiumd_admin_owner:owner-password@db:5432/podiumd_admin"

REQUIRED: dict[str, str] = {
    "PODIUMD_ADMIN_ENVIRONMENT_MUNICIPALITY": "Utrecht",
    "PODIUMD_ADMIN_ENVIRONMENT_STAGE": "accp",
    "PODIUMD_ADMIN_PUBLIC_HOSTNAME": "admin.podiumd.utrecht.example",
    "PODIUMD_ADMIN_OIDC_ISSUER": "https://keycloak.utrecht.example/realms/podiumd",
    "PODIUMD_ADMIN_OIDC_CLIENT_ID": "podiumd-admin",
    "PODIUMD_ADMIN_OIDC_CLIENT_SECRET": "client-secret-value",
    "PODIUMD_ADMIN_DATABASE_APP_URL": APP_URL,
    "PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS": KEY_1,
}


@pytest.fixture
def environ(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A process environment with only the required settings, all valid."""
    for name in list(os.environ):
        if name.upper().startswith("PODIUMD_ADMIN_"):
            monkeypatch.delenv(name)
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _problems(error: pytest.ExceptionInfo[ConfigurationError]) -> dict[str, str]:
    return {problem.setting: problem.message for problem in error.value.problems}


# --- A complete configuration ----------------------------------------------


def test_loads_the_required_settings_with_defaults(environ: pytest.MonkeyPatch) -> None:
    settings = load_settings()

    assert isinstance(settings, Settings)
    assert settings.environment == EnvironmentIdentity("Utrecht", Stage.ACCP)
    assert settings.public_hostname == "admin.podiumd.utrecht.example"
    assert settings.oidc_issuer == "https://keycloak.utrecht.example/realms/podiumd"
    assert settings.oidc_client_id == "podiumd-admin"
    assert settings.oidc_client_secret.get_secret_value() == "client-secret-value"
    assert settings.role_mapping == RoleMapping.for_client("podiumd-admin")
    assert settings.database_app_url.get_secret_value() == APP_URL
    assert [key.get_secret_value() for key in settings.session_encryption_keys] == [KEY_1]
    assert settings.session_timeouts == SessionTimeouts()
    assert settings.session_timeouts.idle_timeout == timedelta(minutes=30)
    assert settings.session_timeouts.absolute_lifetime == timedelta(hours=8)
    assert settings.trusted_proxies == ()


def test_loads_every_optional_setting(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_ENVIRONMENT_LABEL", "Hosting BV")
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLE_CLAIM", "realm_access.roles")
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLES_VIEWER", "admin-viewer")
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLES_OPERATOR", "admin-operator")
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", f"{KEY_1}, {KEY_2}")
    environ.setenv("PODIUMD_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "15")
    environ.setenv("PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES", "720")
    environ.setenv("PODIUMD_ADMIN_TRUSTED_PROXIES", "10.0.0.0/8, 2001:db8::/32,192.0.2.7")

    settings = load_settings()

    assert settings.environment == EnvironmentIdentity("Utrecht", Stage.ACCP, "Hosting BV")
    assert settings.role_mapping == RoleMapping(
        claim_path=("realm_access", "roles"),
        viewer_role_name="admin-viewer",
        operator_role_name="admin-operator",
    )
    assert [key.get_secret_value() for key in settings.session_encryption_keys] == [KEY_1, KEY_2]
    assert settings.session_timeouts == SessionTimeouts(
        idle_timeout=timedelta(minutes=15), absolute_lifetime=timedelta(hours=12)
    )
    assert settings.trusted_proxies == (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("2001:db8::/32"),
        ipaddress.ip_network("192.0.2.7/32"),
    )


def test_secrets_are_masked_in_the_settings_repr(environ: pytest.MonkeyPatch) -> None:
    text = repr(load_settings())

    assert "client-secret-value" not in text
    assert "app-password" not in text
    assert KEY_1 not in text


# --- Missing values ---------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_startup_fails_on_a_missing_required_setting(
    environ: pytest.MonkeyPatch, name: str
) -> None:
    environ.delenv(name)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert _problems(error) == {name: "is required"}
    assert name in str(error.value)


def test_reports_every_missing_setting_at_once(environ: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        environ.delenv(name)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert set(_problems(error)) == set(REQUIRED)


# --- The Environment identity ----------------------------------------------


def test_an_invalid_stage_names_the_stage_setting(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_ENVIRONMENT_STAGE", "production")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    problems = _problems(error)
    assert list(problems) == ["PODIUMD_ADMIN_ENVIRONMENT_STAGE"]
    assert "test, accp, prod" in problems["PODIUMD_ADMIN_ENVIRONMENT_STAGE"]


def test_a_blank_municipality_names_the_municipality_setting(
    environ: pytest.MonkeyPatch,
) -> None:
    environ.setenv("PODIUMD_ADMIN_ENVIRONMENT_MUNICIPALITY", "   ")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert _problems(error) == {"PODIUMD_ADMIN_ENVIRONMENT_MUNICIPALITY": "is required"}


# --- Public hostname --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Admin.PodiumD.Example", "admin.podiumd.example"),
        ("admin.example:8443", "admin.example:8443"),
        ("localhost:8443", "localhost:8443"),
    ],
)
def test_accepts_a_hostname_with_an_optional_port(
    environ: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    environ.setenv("PODIUMD_ADMIN_PUBLIC_HOSTNAME", value)

    assert load_settings().public_hostname == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://admin.example",
        "admin.example/path",
        "user@admin.example",
        "admin..example",
        "-admin.example",
        "admin.example:0",
        "admin.example:99999",
        "admin example",
    ],
)
def test_rejects_a_public_hostname_that_is_not_a_bare_hostname(
    environ: pytest.MonkeyPatch, value: str
) -> None:
    environ.setenv("PODIUMD_ADMIN_PUBLIC_HOSTNAME", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_PUBLIC_HOSTNAME"]


# --- Keycloak ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "http://keycloak.example/realms/podiumd",
        "keycloak.example/realms/podiumd",
        "https://",
        "https://keycloak.example/realms/podiumd?x=1",
        "https://keycloak.example/realms/podiumd#x",
        "https://user:pw@keycloak.example/realms/podiumd",
        "https://keycloak.example:99999/realms/podiumd",
        # Not a loopback address: a naive port strip would read it as ::1.
        "http://[::1:abcd]:8080/realms/podiumd",
        "http://[2001:db8::1]:8080/realms/podiumd",
    ],
)
def test_the_issuer_must_be_an_https_url(environ: pytest.MonkeyPatch, value: str) -> None:
    environ.setenv("PODIUMD_ADMIN_OIDC_ISSUER", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_OIDC_ISSUER"]
    assert "pw" not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:8080/realms/podiumd",
        "http://keycloak.localhost/realms/podiumd",
        "http://127.0.0.1:8080/realms/podiumd",
        "http://[::1]:8080/realms/podiumd",
        "http://[::1]/realms/podiumd",
    ],
)
def test_a_local_development_issuer_may_use_http(environ: pytest.MonkeyPatch, value: str) -> None:
    environ.setenv("PODIUMD_ADMIN_OIDC_ISSUER", value)

    assert load_settings().oidc_issuer == value


def test_a_blank_client_id_is_rejected(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_OIDC_CLIENT_ID", " ")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert _problems(error) == {"PODIUMD_ADMIN_OIDC_CLIENT_ID": "is required"}


def test_a_blank_client_secret_is_rejected(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_OIDC_CLIENT_SECRET", "")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert _problems(error) == {"PODIUMD_ADMIN_OIDC_CLIENT_SECRET": "is required"}


# --- Roles ------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "resource_access..roles", ".roles"])
def test_an_invalid_role_claim_names_the_claim_setting(
    environ: pytest.MonkeyPatch, value: str
) -> None:
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLE_CLAIM", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_AUTH_ROLE_CLAIM"]


@pytest.mark.parametrize(
    "name", ["PODIUMD_ADMIN_AUTH_ROLES_VIEWER", "PODIUMD_ADMIN_AUTH_ROLES_OPERATOR"]
)
def test_a_blank_role_name_names_its_setting(environ: pytest.MonkeyPatch, name: str) -> None:
    environ.setenv(name, "  ")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == [name]


def test_equal_role_names_name_both_role_settings(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLES_VIEWER", "admin")
    environ.setenv("PODIUMD_ADMIN_AUTH_ROLES_OPERATOR", "admin")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == [
        "PODIUMD_ADMIN_AUTH_ROLES_VIEWER, PODIUMD_ADMIN_AUTH_ROLES_OPERATOR"
    ]


# --- Database ---------------------------------------------------------------


def test_a_plain_postgresql_url_uses_the_psycopg_driver(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_DATABASE_APP_URL", "postgresql://app:pw@db/podiumd_admin")

    assert load_settings().database_app_url.get_secret_value() == (
        "postgresql+psycopg://app:pw@db/podiumd_admin"
    )


@pytest.mark.parametrize(
    "value",
    ["mysql://app:secret-pw@db/x", "postgresql+asyncpg://app:secret-pw@db/x", "secret-pw"],
)
def test_a_database_url_for_another_driver_is_rejected_without_echoing_it(
    environ: pytest.MonkeyPatch, value: str
) -> None:
    environ.setenv("PODIUMD_ADMIN_DATABASE_APP_URL", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_DATABASE_APP_URL"]
    assert "secret-pw" not in str(error.value)


def test_the_owner_url_is_not_part_of_the_runtime_settings(environ: pytest.MonkeyPatch) -> None:
    """The Deployment runs with the app role only; the owner URL is for migrations."""
    environ.setenv(DATABASE_OWNER_URL, OWNER_URL)

    text = repr(load_settings())

    assert "owner" not in text


def test_loads_the_owner_url_for_migrations(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_DATABASE_OWNER_URL", OWNER_URL)

    assert DATABASE_OWNER_URL == "PODIUMD_ADMIN_DATABASE_OWNER_URL"
    assert load_owner_database_url() == OWNER_URL


def test_a_missing_owner_url_names_the_setting(environ: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_owner_database_url()

    assert _problems(error) == {"PODIUMD_ADMIN_DATABASE_OWNER_URL": "is required"}


def test_an_invalid_owner_url_is_rejected_without_echoing_it(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_DATABASE_OWNER_URL", "mysql://owner:secret-pw@db/x")

    with pytest.raises(ConfigurationError) as error:
        load_owner_database_url()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_DATABASE_OWNER_URL"]
    assert "secret-pw" not in str(error.value)


# --- Session encryption keys ------------------------------------------------


@pytest.mark.parametrize("value", ["", " , ,"])
def test_at_least_one_encryption_key_is_required(environ: pytest.MonkeyPatch, value: str) -> None:
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert _problems(error) == {"PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS": "is required"}


def test_an_invalid_encryption_key_is_rejected_without_echoing_it(
    environ: pytest.MonkeyPatch,
) -> None:
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", f"{KEY_1},not-a-fernet-key")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    problems = _problems(error)
    assert list(problems) == ["PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS"]
    assert "key 2" in problems["PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS"]
    assert "not-a-fernet-key" not in str(error.value)
    assert KEY_1 not in str(error.value)


def test_the_development_key_is_a_valid_fernet_key() -> None:
    Fernet(DEVELOPMENT_SESSION_ENCRYPTION_KEY)


@pytest.mark.parametrize("position", [0, 1])
def test_startup_fails_on_the_development_key(environ: pytest.MonkeyPatch, position: int) -> None:
    keys = [KEY_1]
    keys.insert(position, DEVELOPMENT_SESSION_ENCRYPTION_KEY)
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", ",".join(keys))

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    problems = _problems(error)
    assert list(problems) == ["PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS"]
    assert (
        f"key {position + 1} is the known development key"
        in (problems["PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS"])
    )
    assert DEVELOPMENT_SESSION_ENCRYPTION_KEY not in str(error.value)


def test_the_development_key_is_recognised_in_standard_base64(
    environ: pytest.MonkeyPatch,
) -> None:
    """The same key bytes in another base64 alphabet are still the development key."""
    standard = base64.b64encode(base64.urlsafe_b64decode(DEVELOPMENT_SESSION_ENCRYPTION_KEY))
    assert standard.decode() != DEVELOPMENT_SESSION_ENCRYPTION_KEY
    Fernet(standard)  # Fernet accepts this spelling too.
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", standard.decode())

    with pytest.raises(ConfigurationError, match="known development key"):
        load_settings()


@pytest.mark.parametrize(
    "hostname",
    ["localhost:8443", "localhost:8080", "podiumd-admin.localhost", "127.0.0.1", "127.0.0.1:8080"],
)
def test_the_development_key_is_accepted_for_a_local_hostname(
    environ: pytest.MonkeyPatch, hostname: str
) -> None:
    """Local development runs on a loopback hostname, which no Environment can use."""
    environ.setenv("PODIUMD_ADMIN_PUBLIC_HOSTNAME", hostname)
    environ.setenv("PODIUMD_ADMIN_SESSION_ENCRYPTION_KEYS", DEVELOPMENT_SESSION_ENCRYPTION_KEY)

    keys = load_settings().session_encryption_keys

    assert [key.get_secret_value() for key in keys] == [DEVELOPMENT_SESSION_ENCRYPTION_KEY]


# --- Session timeouts -------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value", "fragment"),
    [
        ("PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES", "721", "at most 12:00:00"),
        ("PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES", "0", "must be positive"),
        ("PODIUMD_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "-5", "must be positive"),
        ("PODIUMD_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "481", "at most the absolute lifetime"),
        ("PODIUMD_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "thirty", "integer"),
        # Too large for a timedelta: OverflowError, not ValueError.
        ("PODIUMD_ADMIN_SESSION_IDLE_TIMEOUT_MINUTES", "10000000000000", "too large"),
        ("PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES", "10000000000000", "too large"),
    ],
)
def test_invalid_timeouts_name_their_setting(
    environ: pytest.MonkeyPatch, name: str, value: str, fragment: str
) -> None:
    environ.setenv(name, value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    problems = _problems(error)
    assert list(problems) == [name]
    assert fragment in problems[name]


def test_a_too_large_timeout_is_collected_with_the_other_problems(
    environ: pytest.MonkeyPatch,
) -> None:
    environ.setenv("PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES", "10000000000000")
    environ.setenv("PODIUMD_ADMIN_TRUSTED_PROXIES", "not-a-network")

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert sorted(_problems(error)) == [
        "PODIUMD_ADMIN_SESSION_MAX_LIFETIME_MINUTES",
        "PODIUMD_ADMIN_TRUSTED_PROXIES",
    ]


# --- Trusted proxies --------------------------------------------------------


@pytest.mark.parametrize("value", ["10.0.0.0/33", "not-an-address", "10.0.0.0/8,,bad"])
def test_an_invalid_trusted_proxy_is_rejected(environ: pytest.MonkeyPatch, value: str) -> None:
    environ.setenv("PODIUMD_ADMIN_TRUSTED_PROXIES", value)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_TRUSTED_PROXIES"]


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0", "10.0.0.0/8, 0.0.0.0/0"])
def test_trusting_every_address_is_rejected(environ: pytest.MonkeyPatch, value: str) -> None:
    """Trusting every address would let any client choose the recorded client IP."""
    environ.setenv("PODIUMD_ADMIN_TRUSTED_PROXIES", value)

    with pytest.raises(ConfigurationError, match="every address") as error:
        load_settings()

    assert list(_problems(error)) == ["PODIUMD_ADMIN_TRUSTED_PROXIES"]


def test_a_blank_trusted_proxies_value_trusts_none(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("PODIUMD_ADMIN_TRUSTED_PROXIES", "  ")

    assert load_settings().trusted_proxies == ()
