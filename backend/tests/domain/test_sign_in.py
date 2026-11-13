"""The sign-in attempt and the safe return path (task 7.1).

Spec: authentication, "Safe return after sign-in and sign-out": the page a
user returns to is accepted only as a relative path within the Admin Tool
Instance, starting with a single ``/``. Any other value becomes ``/``.
Design D2: a pre-auth record holds ``state``, ``nonce``, the PKCE verifier
and the validated return path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from podiumd_admin.domain.sign_in import (
    MAX_RETURN_PATH_LENGTH,
    SIGN_IN_ATTEMPT_LIFETIME,
    InvalidSignInAttemptError,
    SignInAttempt,
    safe_return_path,
)

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/audit-log",
        "/audit-log?outcome=denied&page=2",
        "/audit-log#entry-1",
        "/a/b/c",
        "/pad%20met%20spatie",
    ],
)
def test_a_relative_path_with_a_single_slash_is_kept(path: str) -> None:
    assert safe_return_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "   ",
        "//evil.example/",
        "https://evil.example/",
        "http://admin.podiumd.onsdorp.example/audit-log",
        "audit-log",
        "/\\evil.example",
        "\\\\evil.example",
        "/\tevil",
        "/audit\nlog",
        " /audit-log",
        "javascript:alert(1)",
        "/" + "a" * MAX_RETURN_PATH_LENGTH,
    ],
)
def test_any_other_return_path_becomes_the_start_page(path: str | None) -> None:
    assert safe_return_path(path) == "/"


def _attempt(**overrides: Any) -> SignInAttempt:
    fields: dict[str, Any] = {
        "state": "state-value-0123456789abcdef",
        "nonce": "nonce-value-0123456789abcdef",
        "code_verifier": "v" * 64,
        "return_path": "/audit-log",
        "created_at": NOW,
    }
    fields.update(overrides)
    return SignInAttempt(**fields)


def test_an_attempt_holds_state_nonce_verifier_and_return_path() -> None:
    attempt = _attempt()

    assert attempt.state == "state-value-0123456789abcdef"
    assert attempt.nonce == "nonce-value-0123456789abcdef"
    assert attempt.code_verifier == "v" * 64
    assert attempt.return_path == "/audit-log"
    assert attempt.expires_at == NOW + SIGN_IN_ATTEMPT_LIFETIME


def test_an_attempt_replaces_an_unsafe_return_path() -> None:
    assert _attempt(return_path="//evil.example/").return_path == "/"


def test_an_attempt_expires() -> None:
    attempt = _attempt()

    assert not attempt.is_expired(NOW + SIGN_IN_ATTEMPT_LIFETIME - timedelta(seconds=1))
    assert attempt.is_expired(NOW + SIGN_IN_ATTEMPT_LIFETIME)


def test_secrets_never_appear_in_the_repr() -> None:
    text = repr(_attempt())

    assert "state-value" not in text
    assert "nonce-value" not in text
    assert "v" * 64 not in text


@pytest.mark.parametrize("field", ["state", "nonce", "code_verifier"])
@pytest.mark.parametrize("value", ["", "   ", None, 42])
def test_an_attempt_needs_its_random_values(field: str, value: object) -> None:
    with pytest.raises(InvalidSignInAttemptError, match=field):
        _attempt(**{field: value})


@pytest.mark.parametrize("verifier", ["v" * 42, "v" * 129, "v" * 60 + "!!!!"])
def test_the_verifier_follows_rfc_7636(verifier: str) -> None:
    with pytest.raises(InvalidSignInAttemptError, match="code_verifier"):
        _attempt(code_verifier=verifier)


def test_an_attempt_needs_an_aware_timestamp() -> None:
    with pytest.raises(InvalidSignInAttemptError, match="created_at"):
        _attempt(created_at=datetime(2026, 11, 13, 9, 0))  # noqa: DTZ001 - the invalid case
