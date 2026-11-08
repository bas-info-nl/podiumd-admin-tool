"""Sessions: what the server keeps about a signed-in user.

Spec: authentication, "Sessions are held by the server". Design D2: tokens
stay server-side, and a Session knows its user, roles, Keycloak ``sid`` and
the moments that decide idle and absolute expiry.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import (
    MAX_KEYCLOAK_SESSION_ID_LENGTH,
    InvalidSessionError,
    Session,
    SessionTokens,
)

CREATED_AT = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


def _tokens(**overrides: Any) -> SessionTokens:
    fields: dict[str, Any] = {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "id_token": "id-secret",
        "access_token_expires_at": CREATED_AT + timedelta(minutes=5),
    }
    fields.update(overrides)
    return SessionTokens(**fields)


def _session(**overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": "f3b2c1d0-0000-4000-8000-000000000001",
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER}),
        "created_at": CREATED_AT,
        "last_seen_at": CREATED_AT,
        "expires_at": CREATED_AT + timedelta(hours=8),
        "tokens": _tokens(),
    }
    fields.update(overrides)
    return Session(**fields)


# --- SessionTokens --------------------------------------------------------------


def test_tokens_never_show_up_in_their_repr() -> None:
    text = repr(_tokens())

    assert "secret" not in text
    assert "access_token_expires_at" in text


def test_refresh_and_id_tokens_are_optional() -> None:
    tokens = _tokens(refresh_token=None, id_token=None)

    assert tokens.refresh_token is None
    assert tokens.id_token is None


@pytest.mark.parametrize("value", [None, "", 42])
def test_an_access_token_is_required(value: Any) -> None:
    with pytest.raises(InvalidSessionError, match="access_token"):
        _tokens(access_token=value)


@pytest.mark.parametrize("field", ["refresh_token", "id_token"])
@pytest.mark.parametrize("value", ["", 42])
def test_optional_tokens_must_be_non_empty_text(field: str, value: Any) -> None:
    with pytest.raises(InvalidSessionError, match=field):
        _tokens(**{field: value})


def test_the_access_token_expiry_is_converted_to_utc() -> None:
    expiry = datetime(2026, 11, 8, 10, 5, tzinfo=timezone(timedelta(hours=1)))

    assert _tokens(access_token_expires_at=expiry).access_token_expires_at == datetime(
        2026, 11, 8, 9, 5, tzinfo=UTC
    )


def test_a_naive_access_token_expiry_is_rejected() -> None:
    with pytest.raises(InvalidSessionError, match="access_token_expires_at"):
        _tokens(access_token_expires_at=datetime(2026, 11, 8, 9, 5))  # noqa: DTZ001


# --- Session --------------------------------------------------------------------


def test_a_session_keeps_what_it_was_given() -> None:
    session = _session()

    assert session.user_subject == "f3b2c1d0-0000-4000-8000-000000000001"
    assert session.username == "j.jansen"
    assert session.keycloak_session_id == "kc-sid-1"
    assert session.roles == frozenset({Role.VIEWER})
    assert session.tokens == _tokens()


def test_a_session_repr_shows_no_tokens() -> None:
    assert "secret" not in repr(_session())


def test_a_session_without_tokens_is_one_whose_tokens_were_purged() -> None:
    assert _session(tokens=None).tokens is None


@pytest.mark.parametrize("value", [None, "", "   ", 42])
def test_a_user_subject_is_required(value: Any) -> None:
    with pytest.raises(InvalidSessionError, match="user_subject"):
        _session(user_subject=value)


@pytest.mark.parametrize("field", ["username", "keycloak_session_id"])
def test_optional_text_is_trimmed_and_blank_means_absent(field: str) -> None:
    assert getattr(_session(**{field: "  x  "}), field) == "x"
    assert getattr(_session(**{field: "  "}), field) is None
    assert getattr(_session(**{field: None}), field) is None


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("user_subject", 255),
        ("username", 255),
        ("keycloak_session_id", MAX_KEYCLOAK_SESSION_ID_LENGTH),
    ],
)
def test_text_longer_than_its_column_is_rejected(field: str, limit: int) -> None:
    assert getattr(_session(**{field: "a" * limit}), field) == "a" * limit

    with pytest.raises(InvalidSessionError, match=field):
        _session(**{field: "a" * (limit + 1)})


@pytest.mark.parametrize("field", ["username", "keycloak_session_id"])
def test_optional_text_must_be_text(field: str) -> None:
    with pytest.raises(InvalidSessionError, match=field):
        _session(**{field: 42})


def test_roles_are_copied_into_a_frozenset() -> None:
    session = _session(roles={Role.OPERATOR, Role.VIEWER})

    assert session.roles == frozenset({Role.OPERATOR, Role.VIEWER})
    assert isinstance(session.roles, frozenset)


def test_a_session_may_hold_no_roles() -> None:
    assert _session(roles=frozenset()).roles == frozenset()


@pytest.mark.parametrize("roles", [frozenset({"viewer"}), "viewer", None])
def test_roles_must_be_a_set_of_roles(roles: Any) -> None:
    with pytest.raises(InvalidSessionError, match="roles"):
        _session(roles=roles)


@pytest.mark.parametrize("field", ["created_at", "last_seen_at", "expires_at"])
def test_moments_must_be_timezone_aware(field: str) -> None:
    with pytest.raises(InvalidSessionError, match=field):
        _session(**{field: datetime(2026, 11, 8, 9, 0)})  # noqa: DTZ001


def test_moments_are_converted_to_utc() -> None:
    plus_one = timezone(timedelta(hours=1))

    session = _session(
        created_at=datetime(2026, 11, 8, 10, 0, tzinfo=plus_one),
        last_seen_at=datetime(2026, 11, 8, 10, 0, tzinfo=plus_one),
        expires_at=datetime(2026, 11, 8, 18, 0, tzinfo=plus_one),
    )

    assert session.created_at == CREATED_AT
    assert session.created_at.tzinfo is UTC
    assert session.last_seen_at.tzinfo is UTC
    assert session.expires_at == CREATED_AT + timedelta(hours=8)


def test_a_session_cannot_be_seen_before_it_was_created() -> None:
    with pytest.raises(InvalidSessionError, match="last_seen_at"):
        _session(last_seen_at=CREATED_AT - timedelta(seconds=1))


def test_a_session_must_expire_after_it_was_created() -> None:
    with pytest.raises(InvalidSessionError, match="expires_at"):
        _session(expires_at=CREATED_AT)


def test_tokens_must_be_session_tokens() -> None:
    with pytest.raises(InvalidSessionError, match="tokens"):
        _session(tokens={"access_token": "x"})


def test_a_session_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _session().username = "other"  # type: ignore[misc]
