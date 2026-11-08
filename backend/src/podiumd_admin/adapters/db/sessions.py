"""Sessions in PostgreSQL: the ``SessionStore`` port (design D2).

The ``sessions`` row is keyed by the SHA-256 digest of the session
identifier; the identifier itself is never stored. The tokens are stored
encrypted with ``MultiFernet`` (see ``session_crypto``).

The store works on the caller's connection and never commits, like the audit
repository, so ending a session and recording that can share one unit of work
(design D4).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from podiumd_admin.adapters.db.session_crypto import (
    TokenCipher,
    TokenDecryptionError,
    hash_session_id,
)
from podiumd_admin.adapters.db.tables import sessions
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session


class SqlSessionStore:
    """Keeps Sessions on the caller's connection, found by the session identifier."""

    def __init__(self, connection: AsyncConnection, cipher: TokenCipher) -> None:
        self._connection = connection
        self._cipher = cipher

    async def add(self, session_id: str, session: Session) -> None:
        """Store ``session`` under the hash of ``session_id``.

        Raises ``ValueError`` for a blank identifier and ``IntegrityError`` if
        the identifier is already in use.
        """
        await self._connection.execute(
            insert(sessions).values(
                id_hash=hash_session_id(session_id),
                user_subject=session.user_subject,
                username=session.username,
                keycloak_session_id=session.keycloak_session_id,
                roles=sorted(role.value for role in session.roles),
                created_at=session.created_at,
                last_seen_at=session.last_seen_at,
                expires_at=session.expires_at,
                tokens=(
                    self._cipher.encrypt(session.tokens) if session.tokens is not None else None
                ),
            )
        )

    async def get(self, session_id: str) -> Session | None:
        """Return the Session for ``session_id``, or ``None`` if it is not known.

        A blank identifier is never known. A session whose tokens cannot be
        decrypted with the configured keys (the key was rotated out) counts
        as unknown too: design D2 accepts that its user signs in again.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        result = await self._connection.execute(
            select(sessions).where(sessions.c.id_hash == hash_session_id(session_id))
        )
        row = result.one_or_none()
        if row is None:
            return None
        try:
            return self._to_session(row)
        except TokenDecryptionError:
            return None

    def _to_session(self, row: Row[Any]) -> Session:
        return Session(
            user_subject=row.user_subject,
            username=row.username,
            keycloak_session_id=row.keycloak_session_id,
            roles=frozenset(Role(role) for role in row.roles),
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            tokens=self._cipher.decrypt(row.tokens) if row.tokens is not None else None,
        )
