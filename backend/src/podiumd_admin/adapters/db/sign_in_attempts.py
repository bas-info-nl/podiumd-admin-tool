"""Sign-in attempts in PostgreSQL: the ``SignInAttemptStore`` port (design D2).

The row is keyed by the SHA-256 digest of the attempt identifier in the
browser's sign-in cookie, like a session. ``take`` deletes the row and
returns it in one statement, so two callbacks can never both use one attempt.

The store works on the caller's connection and never commits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncConnection

from podiumd_admin.adapters.db.session_crypto import hash_session_id
from podiumd_admin.adapters.db.tables import sign_in_attempts
from podiumd_admin.domain.sign_in import SignInAttempt


class SqlSignInAttemptStore:
    """Keeps sign-in attempts on the caller's connection."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def add(self, attempt_id: str, attempt: SignInAttempt) -> None:
        await self._connection.execute(
            insert(sign_in_attempts).values(
                id_hash=hash_session_id(attempt_id),
                state=attempt.state,
                nonce=attempt.nonce,
                code_verifier=attempt.code_verifier,
                return_path=attempt.return_path,
                created_at=attempt.created_at,
                expires_at=attempt.expires_at,
            )
        )

    async def take(self, attempt_id: str) -> SignInAttempt | None:
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            return None
        result = await self._connection.execute(
            delete(sign_in_attempts)
            .where(sign_in_attempts.c.id_hash == hash_session_id(attempt_id))
            .returning(sign_in_attempts)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return SignInAttempt(
            state=row.state,
            nonce=row.nonce,
            code_verifier=row.code_verifier,
            return_path=row.return_path,
            created_at=row.created_at,
        )

    async def purge_expired(self, now: datetime) -> int:
        result = await self._connection.execute(
            delete(sign_in_attempts).where(sign_in_attempts.c.expires_at <= now)
        )
        return result.rowcount
