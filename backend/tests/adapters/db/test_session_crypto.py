"""Session identifier hashing and token encryption (task 4.4, design D2).

The ``sessions`` table is keyed by SHA-256 of the session identifier, and the
tokens are encrypted with ``MultiFernet``: the first key encrypts, every key
decrypts, so keys can be rotated. These tests need no database.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from podiumd_admin.adapters.db.session_crypto import (
    InvalidTokenKeyError,
    TokenCipher,
    TokenDecryptionError,
    hash_session_id,
)
from podiumd_admin.domain.session import SessionTokens

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()

TOKENS = SessionTokens(
    access_token="access-plaintext",  # noqa: S106 - a test value, not a secret
    refresh_token="refresh-plaintext",  # noqa: S106 - a test value, not a secret
    id_token="id-plaintext",  # noqa: S106 - a test value, not a secret
    access_token_expires_at=datetime(2026, 11, 8, 9, 5, tzinfo=UTC),
)


# --- hash_session_id ----------------------------------------------------------------


def test_the_session_id_is_hashed_with_sha256() -> None:
    session_id = "dGhpcy1pcy1hLXNlc3Npb24taWQ"

    assert hash_session_id(session_id) == hashlib.sha256(session_id.encode()).digest()
    assert len(hash_session_id(session_id)) == 32


def test_different_session_ids_get_different_hashes() -> None:
    assert hash_session_id("session-a") != hash_session_id("session-b")


@pytest.mark.parametrize("session_id", ["", "   "])
def test_a_blank_session_id_is_rejected(session_id: str) -> None:
    with pytest.raises(ValueError, match="session id"):
        hash_session_id(session_id)


# --- TokenCipher --------------------------------------------------------------------


def test_tokens_survive_encryption_and_decryption() -> None:
    cipher = TokenCipher([NEW_KEY])

    assert cipher.decrypt(cipher.encrypt(TOKENS)) == TOKENS


def test_optional_tokens_stay_absent() -> None:
    cipher = TokenCipher([NEW_KEY])
    tokens = SessionTokens(
        access_token="access-plaintext",  # noqa: S106 - a test value, not a secret
        refresh_token=None,
        id_token=None,
        access_token_expires_at=TOKENS.access_token_expires_at,
    )

    assert cipher.decrypt(cipher.encrypt(tokens)) == tokens


def test_the_ciphertext_holds_no_token_in_plain_text() -> None:
    ciphertext = TokenCipher([NEW_KEY]).encrypt(TOKENS)

    assert b"plaintext" not in ciphertext


def test_encrypting_twice_gives_different_ciphertexts() -> None:
    cipher = TokenCipher([NEW_KEY])

    assert cipher.encrypt(TOKENS) != cipher.encrypt(TOKENS)


def test_tokens_encrypted_with_an_older_key_decrypt_after_rotation() -> None:
    before_rotation = TokenCipher([OLD_KEY]).encrypt(TOKENS)

    assert TokenCipher([NEW_KEY, OLD_KEY]).decrypt(before_rotation) == TOKENS


def test_the_first_key_encrypts() -> None:
    ciphertext = TokenCipher([NEW_KEY, OLD_KEY]).encrypt(TOKENS)

    assert TokenCipher([NEW_KEY]).decrypt(ciphertext) == TOKENS
    with pytest.raises(TokenDecryptionError):
        TokenCipher([OLD_KEY]).decrypt(ciphertext)


def test_tokens_from_a_key_no_longer_configured_cannot_be_decrypted() -> None:
    ciphertext = TokenCipher([OLD_KEY]).encrypt(TOKENS)

    with pytest.raises(TokenDecryptionError):
        TokenCipher([NEW_KEY]).decrypt(ciphertext)


def test_a_tampered_ciphertext_is_rejected() -> None:
    ciphertext = bytearray(TokenCipher([NEW_KEY]).encrypt(TOKENS))
    ciphertext[-5] ^= 0x01

    with pytest.raises(TokenDecryptionError):
        TokenCipher([NEW_KEY]).decrypt(bytes(ciphertext))


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[]", b'{"access_token": "x"}', b'{"access_token": "", "refresh_token": null}'],
)
def test_a_decrypted_payload_that_is_not_tokens_is_rejected(payload: bytes) -> None:
    ciphertext = Fernet(NEW_KEY.encode()).encrypt(payload)

    with pytest.raises(TokenDecryptionError):
        TokenCipher([NEW_KEY]).decrypt(ciphertext)


def test_at_least_one_key_is_required() -> None:
    with pytest.raises(InvalidTokenKeyError, match="at least one"):
        TokenCipher([])


def test_an_invalid_key_is_rejected_without_revealing_it() -> None:
    with pytest.raises(InvalidTokenKeyError) as raised:
        TokenCipher([NEW_KEY, "not-a-fernet-key-but-a-secret"])

    assert "not-a-fernet-key-but-a-secret" not in str(raised.value)
    assert "key 2" in str(raised.value)
