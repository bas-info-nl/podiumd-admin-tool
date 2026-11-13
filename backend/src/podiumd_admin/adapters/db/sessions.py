"""Sessions in PostgreSQL: the ``SessionStore`` port (design D2).

The ``sessions`` row is keyed by the SHA-256 digest of the session
identifier; the identifier itself is never stored. The tokens are stored
encrypted with ``MultiFernet`` (see ``session_crypto``).

The store works on the caller's connection and never commits, like the audit
repository, so ending a session and recording that can share one unit of work
(design D4).

Removing a session deletes its row, which purges its tokens. The opaque ref
of a ``StoredSession`` is the hex form of the row key, the hash: it cannot be
presented as a session identifier.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Row, delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from podiumd_admin.adapters.db.session_crypto import (
    TokenCipher,
    TokenDecryptionError,
    hash_session_id,
)
from podiumd_admin.adapters.db.tables import SESSION_ID_HASH_LENGTH, sessions
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from podiumd_admin.ports.session import StoredSession


def _ref_hash(ref: str) -> bytes | None:
    """The ``id_hash`` a ref stands for, or ``None`` if ``ref`` is not one."""
    try:
        id_hash = bytes.fromhex(ref)
    except ValueError:
        return None
    return id_hash if len(id_hash) == SESSION_ID_HASH_LENGTH else None


def _known(session_id: str) -> bool:
    return isinstance(session_id, str) and bool(session_id.strip())


class SqlSessionStore:
    """Keeps Sessions on the caller's connection, found by the session identifier."""

    def __init__(self, connection: AsyncConnection, cipher: TokenCipher) -> None:
        self._connection = connection
        self._cipher = cipher

    def _values(self, session: Session) -> dict[str, Any]:
        return {
            "user_subject": session.user_subject,
            "username": session.username,
            "keycloak_session_id": session.keycloak_session_id,
            "roles": sorted(role.value for role in session.roles),
            "created_at": session.created_at,
            "last_seen_at": session.last_seen_at,
            "expires_at": session.expires_at,
            "tokens": (
                self._cipher.encrypt(session.tokens) if session.tokens is not None else None
            ),
        }

    async def add(self, session_id: str, session: Session) -> None:
        """Store ``session`` under the hash of ``session_id``.

        Raises ``ValueError`` for a blank identifier and ``IntegrityError`` if
        the identifier is already in use.
        """
        await self._connection.execute(
            insert(sessions).values(id_hash=hash_session_id(session_id), **self._values(session))
        )

    async def save(self, session_id: str, session: Session) -> bool:
        """Replace the stored Session; ``False`` if it is no longer stored."""
        if not _known(session_id):
            return False
        result = await self._connection.execute(
            update(sessions)
            .where(sessions.c.id_hash == hash_session_id(session_id))
            .values(**self._values(session))
        )
        return result.rowcount == 1

    async def remove(self, session_id: str) -> bool:
        """Delete the row, and with it the tokens; ``False`` if there was none."""
        if not _known(session_id):
            return False
        return await self._delete(hash_session_id(session_id))

    async def remove_by_ref(self, ref: str) -> bool:
        id_hash = _ref_hash(ref)
        return id_hash is not None and await self._delete(id_hash)

    async def _delete(self, id_hash: bytes) -> bool:
        result = await self._connection.execute(
            delete(sessions).where(sessions.c.id_hash == id_hash)
        )
        return result.rowcount == 1

    async def find_by_keycloak_session_id(self, keycloak_session_id: str) -> list[StoredSession]:
        result = await self._connection.execute(
            select(sessions).where(sessions.c.keycloak_session_id == keycloak_session_id)
        )
        return [self._stored(row) for row in result]

    async def find_expired(
        self, *, last_seen_before: datetime, now: datetime, limit: int
    ) -> list[StoredSession]:
        result = await self._connection.execute(
            select(sessions)
            .where(or_(sessions.c.last_seen_at < last_seen_before, sessions.c.expires_at <= now))
            .order_by(sessions.c.last_seen_at)
            .limit(limit)
        )
        return [self._stored(row) for row in result]

    def _stored(self, row: Row[Any]) -> StoredSession:
        """A found session; tokens that cannot be decrypted count as purged.

        The session must still be found, or a session whose key was rotated
        out would never be ended and recorded.
        """
        try:
            session = self._to_session(row)
        except TokenDecryptionError:
            session = self._to_session(row, with_tokens=False)
        return StoredSession(ref=bytes(row.id_hash).hex(), session=session)

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

    def _to_session(self, row: Row[Any], *, with_tokens: bool = True) -> Session:
        return Session(
            user_subject=row.user_subject,
            username=row.username,
            keycloak_session_id=row.keycloak_session_id,
            roles=frozenset(Role(role) for role in row.roles),
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            tokens=(
                self._cipher.decrypt(row.tokens) if with_tokens and row.tokens is not None else None
            ),
        )
