"""Hashing session identifiers and encrypting session tokens (design D2).

- The ``sessions`` table is keyed by the SHA-256 digest of the session
  identifier, so a copy of the table does not reveal identifiers a browser
  could present. The identifier is a high-entropy random value, so a plain
  hash is enough; no salt or slow hash is needed.
- The OIDC tokens are encrypted with ``MultiFernet``. The first key encrypts;
  every key decrypts, so a new key can be put in front and an old one removed
  later. Sessions whose key was removed can no longer be read, so their users
  sign in again.

No error message here ever includes a key or token value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from podiumd_admin.domain.session import InvalidSessionError, SessionTokens


class InvalidTokenKeyError(ValueError):
    """The configured token encryption keys are missing or invalid."""


class TokenDecryptionError(Exception):
    """Stored tokens could not be decrypted: unknown key, tampering or a bad payload."""


def hash_session_id(session_id: str) -> bytes:
    """Return the SHA-256 digest of ``session_id``, the key of its ``sessions`` row."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("a session id must be non-blank text")
    return hashlib.sha256(session_id.encode("utf-8")).digest()


def _fernet(index: int, key: str) -> Fernet:
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        # Fernet's own message is generic, but never risk echoing the key.
        raise InvalidTokenKeyError(
            f"token encryption key {index} is not a valid Fernet key "
            "(32 url-safe base64-encoded bytes)"
        ) from None


def _tokens_from(payload: Any) -> SessionTokens:
    if not isinstance(payload, dict):
        raise TokenDecryptionError("stored tokens are not an object")
    try:
        return SessionTokens(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            id_token=payload["id_token"],
            access_token_expires_at=datetime.fromisoformat(payload["access_token_expires_at"]),
        )
    except (KeyError, TypeError, ValueError, InvalidSessionError):
        raise TokenDecryptionError("stored tokens are incomplete or invalid") from None


class TokenCipher:
    """Encrypts and decrypts ``SessionTokens`` with ``MultiFernet``.

    ``keys`` are Fernet keys, newest first: the first encrypts, all decrypt.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise InvalidTokenKeyError("at least one token encryption key is required")
        self._fernet = MultiFernet([_fernet(index, key) for index, key in enumerate(keys, start=1)])

    def encrypt(self, tokens: SessionTokens) -> bytes:
        payload = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "id_token": tokens.id_token,
            "access_token_expires_at": tokens.access_token_expires_at.isoformat(),
        }
        return self._fernet.encrypt(json.dumps(payload).encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> SessionTokens:
        try:
            plaintext = self._fernet.decrypt(ciphertext)
        except InvalidToken:
            raise TokenDecryptionError(
                "stored tokens could not be decrypted with the configured keys"
            ) from None
        try:
            payload = json.loads(plaintext)
        except ValueError:
            raise TokenDecryptionError("stored tokens are not valid JSON") from None
        return _tokens_from(payload)
