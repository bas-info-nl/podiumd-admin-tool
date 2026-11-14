"""What Keycloak vouches for: ``VerifiedIdentity`` and ``LogoutNotice`` (design D2, D3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from podiumd_admin.domain.identity import LogoutNotice, VerifiedIdentity
from podiumd_admin.domain.session import SessionTokens

TOKENS = SessionTokens(
    access_token="access-1",  # noqa: S106 - a test value, not a secret
    refresh_token=None,
    id_token=None,
    access_token_expires_at=datetime(2026, 11, 13, 9, 5, tzinfo=UTC),
)


def test_the_claims_are_a_read_only_copy() -> None:
    claims: dict[str, object] = {"resource_access": {"podiumd-admin": {"roles": ["viewer"]}}}
    identity = VerifiedIdentity(
        subject="f3b2c1d0",
        username="j.jansen",
        keycloak_session_id=None,
        tokens=TOKENS,
        claims=claims,
    )
    claims["extra"] = True

    assert "extra" not in identity.claims
    with pytest.raises(TypeError):
        identity.claims["extra"] = True  # type: ignore[index]


def test_claims_default_to_none_and_stay_out_of_the_repr() -> None:
    identity = VerifiedIdentity(
        subject="f3b2c1d0", username=None, keycloak_session_id=None, tokens=TOKENS
    )

    assert dict(identity.claims) == {}
    assert "access-1" not in repr(identity)


@pytest.mark.parametrize("subject", ["", "  ", None])
def test_an_identity_needs_a_subject(subject: object) -> None:
    with pytest.raises(ValueError, match="subject"):
        VerifiedIdentity(
            subject=subject,  # type: ignore[arg-type]
            username=None,
            keycloak_session_id=None,
            tokens=TOKENS,
        )


def test_an_identity_needs_tokens() -> None:
    with pytest.raises(ValueError, match="tokens"):
        VerifiedIdentity(
            subject="f3b2c1d0",
            username=None,
            keycloak_session_id=None,
            tokens="access-1",  # type: ignore[arg-type]
        )


def test_a_logout_notice_names_a_keycloak_session() -> None:
    assert LogoutNotice("kc-sid-1").keycloak_session_id == "kc-sid-1"
    with pytest.raises(ValueError, match="keycloak_session_id"):
        LogoutNotice(" ")
