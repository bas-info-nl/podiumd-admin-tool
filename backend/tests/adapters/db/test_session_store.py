"""SqlSessionStore: Sessions in PostgreSQL (task 4.4, design D2).

Spec: authentication, "Sessions are held by the server": tokens are kept
encrypted at rest and only a hash of each session identifier is stored. A
session identifier the store does not know is never adopted.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg.errors
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.session_crypto import TokenCipher
from podiumd_admin.adapters.db.sessions import SqlSessionStore
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session, SessionTokens
from podiumd_admin.ports.session import SessionStore

pytestmark = pytest.mark.integration

SESSION_ID = "k3Jd9-opaque-random-session-identifier"
OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()
CREATED_AT = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)

TOKENS = SessionTokens(
    access_token="access-plaintext",  # noqa: S106 - a test value, not a secret
    refresh_token="refresh-plaintext",  # noqa: S106 - a test value, not a secret
    id_token="id-plaintext",  # noqa: S106 - a test value, not a secret
    access_token_expires_at=CREATED_AT + timedelta(minutes=5),
)


def _session(**overrides: Any) -> Session:
    fields: dict[str, Any] = {
        "user_subject": "f3b2c1d0-0000-4000-8000-000000000001",
        "username": "j.jansen",
        "keycloak_session_id": "kc-sid-1",
        "roles": frozenset({Role.VIEWER, Role.OPERATOR}),
        "created_at": CREATED_AT,
        "last_seen_at": CREATED_AT + timedelta(minutes=1),
        "expires_at": CREATED_AT + timedelta(hours=8),
        "tokens": TOKENS,
    }
    fields.update(overrides)
    return Session(**fields)


async def _add(
    engine: AsyncEngine, session_id: str, session: Session, keys: list[str] | None = None
) -> None:
    async with engine.begin() as connection:
        store: SessionStore = SqlSessionStore(connection, TokenCipher(keys or [NEW_KEY]))
        await store.add(session_id, session)


async def _get(
    engine: AsyncEngine, session_id: str, keys: list[str] | None = None
) -> Session | None:
    async with engine.connect() as connection:
        store: SessionStore = SqlSessionStore(connection, TokenCipher(keys or [NEW_KEY]))
        return await store.get(session_id)


async def _raw_rows(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT * FROM sessions"))
        return [dict(row._mapping) for row in result]


async def test_a_stored_session_is_found_by_its_session_id(app_engine: AsyncEngine) -> None:
    session = _session()

    await _add(app_engine, SESSION_ID, session)

    assert await _get(app_engine, SESSION_ID) == session


async def test_a_session_without_roles_or_optional_fields_is_found(
    app_engine: AsyncEngine,
) -> None:
    session = _session(roles=frozenset(), username=None, keycloak_session_id=None)

    await _add(app_engine, SESSION_ID, session)

    assert await _get(app_engine, SESSION_ID) == session


async def test_a_session_whose_tokens_were_purged_is_found(app_engine: AsyncEngine) -> None:
    session = _session(tokens=None)

    await _add(app_engine, SESSION_ID, session)

    assert await _get(app_engine, SESSION_ID) == session


async def test_the_row_is_keyed_by_the_sha256_of_the_session_id(app_engine: AsyncEngine) -> None:
    await _add(app_engine, SESSION_ID, _session())

    [row] = await _raw_rows(app_engine)

    assert bytes(row["id_hash"]) == hashlib.sha256(SESSION_ID.encode()).digest()


async def test_neither_the_session_id_nor_a_token_is_stored_in_plain_text(
    app_engine: AsyncEngine,
) -> None:
    await _add(app_engine, SESSION_ID, _session())

    [row] = await _raw_rows(app_engine)
    stored = b"".join(
        bytes(value) if isinstance(value, bytes | memoryview) else str(value).encode()
        for value in row.values()
    )

    assert SESSION_ID.encode() not in stored
    assert b"plaintext" not in stored


@pytest.mark.parametrize("session_id", ["never-issued", "", SESSION_ID.upper()])
async def test_an_unknown_session_id_finds_nothing(
    app_engine: AsyncEngine, session_id: str
) -> None:
    await _add(app_engine, SESSION_ID, _session())

    assert await _get(app_engine, session_id) is None


async def test_tokens_stored_before_a_key_rotation_are_still_readable(
    app_engine: AsyncEngine,
) -> None:
    await _add(app_engine, SESSION_ID, _session(), keys=[OLD_KEY])

    found = await _get(app_engine, SESSION_ID, keys=[NEW_KEY, OLD_KEY])

    assert found is not None
    assert found.tokens == TOKENS


async def test_a_session_whose_key_was_removed_is_no_longer_found(
    app_engine: AsyncEngine,
) -> None:
    """Design D2: rotating the key out invalidates the session; the user signs in again."""
    await _add(app_engine, SESSION_ID, _session(), keys=[OLD_KEY])

    assert await _get(app_engine, SESSION_ID, keys=[NEW_KEY]) is None


async def test_a_session_id_is_stored_only_once(app_engine: AsyncEngine) -> None:
    await _add(app_engine, SESSION_ID, _session())

    with pytest.raises(IntegrityError):
        await _add(app_engine, SESSION_ID, _session(username="someone-else"))


async def test_a_blank_session_id_cannot_be_stored(app_engine: AsyncEngine) -> None:
    with pytest.raises(ValueError, match="session id"):
        await _add(app_engine, "", _session())


async def test_adding_runs_in_the_callers_transaction(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as connection:
        await SqlSessionStore(connection, TokenCipher([NEW_KEY])).add(SESSION_ID, _session())
        await connection.rollback()

    assert await _get(app_engine, SESSION_ID) is None


# --- The database repeats the domain's rules --------------------------------------


@pytest.mark.parametrize(
    ("id_hash", "roles"),
    [
        pytest.param(b"\x00" * 31, ["viewer"], id="hash not 32 bytes"),
        pytest.param(b"\x00" * 32, ["admin"], id="unknown role"),
    ],
)
async def test_the_database_rejects_malformed_sessions(
    app_engine: AsyncEngine, id_hash: bytes, roles: list[str]
) -> None:
    with pytest.raises(IntegrityError) as raised:
        async with app_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO sessions (id_hash, user_subject, roles, created_at,"
                    " last_seen_at, expires_at) VALUES (:id_hash, 'subject', :roles,"
                    " :created_at, :created_at, :expires_at)"
                ),
                {
                    "id_hash": id_hash,
                    "roles": roles,
                    "created_at": CREATED_AT,
                    "expires_at": CREATED_AT + timedelta(hours=8),
                },
            )

    assert isinstance(raised.value.orig, psycopg.errors.CheckViolation)
