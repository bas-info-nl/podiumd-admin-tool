"""SqlSignInAttemptStore: pre-auth records in PostgreSQL (task 7.1, design D2).

An attempt is found by the identifier in the browser's sign-in cookie; only
its SHA-256 digest is stored. Taking an attempt removes it, so a callback can
use it once.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.sign_in_attempts import SqlSignInAttemptStore
from podiumd_admin.domain.sign_in import SIGN_IN_ATTEMPT_LIFETIME, SignInAttempt
from podiumd_admin.ports.sign_in import SignInAttemptStore

pytestmark = pytest.mark.integration

ATTEMPT_ID = "attempt-id-from-the-sign-in-cookie-0123456789"
CREATED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _attempt(created_at: datetime = CREATED_AT) -> SignInAttempt:
    return SignInAttempt(
        state="state-value-0123456789abcdef",
        nonce="nonce-value-0123456789abcdef",
        code_verifier="v" * 43,
        return_path="/audit-log?outcome=denied",
        created_at=created_at,
    )


async def test_an_attempt_is_taken_once(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        store: SignInAttemptStore = SqlSignInAttemptStore(connection)
        await store.add(ATTEMPT_ID, _attempt())

    async with app_engine.begin() as connection:
        first = await SqlSignInAttemptStore(connection).take(ATTEMPT_ID)
        second = await SqlSignInAttemptStore(connection).take(ATTEMPT_ID)

    assert first == _attempt()
    assert second is None


@pytest.mark.parametrize("attempt_id", ["unknown-attempt-id", "", "   "])
async def test_an_unknown_attempt_is_none(app_engine: AsyncEngine, attempt_id: str) -> None:
    async with app_engine.begin() as connection:
        assert await SqlSignInAttemptStore(connection).take(attempt_id) is None


async def test_only_the_hash_of_the_identifier_is_stored(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        await SqlSignInAttemptStore(connection).add(ATTEMPT_ID, _attempt())
        stored = (
            await connection.execute(text("SELECT id_hash, expires_at FROM sign_in_attempts"))
        ).one()

    assert bytes(stored.id_hash) == hashlib.sha256(ATTEMPT_ID.encode()).digest()
    assert stored.expires_at == CREATED_AT + SIGN_IN_ATTEMPT_LIFETIME


async def test_expired_attempts_are_purged(app_engine: AsyncEngine) -> None:
    now = CREATED_AT + SIGN_IN_ATTEMPT_LIFETIME
    async with app_engine.begin() as connection:
        store = SqlSignInAttemptStore(connection)
        await store.add("expired-attempt", _attempt(CREATED_AT))
        await store.add("open-attempt", _attempt(CREATED_AT + timedelta(minutes=1)))

    async with app_engine.begin() as connection:
        purged = await SqlSignInAttemptStore(connection).purge_expired(now)

    async with app_engine.begin() as connection:
        store = SqlSignInAttemptStore(connection)
        assert purged == 1
        assert await store.take("expired-attempt") is None
        assert await store.take("open-attempt") is not None
