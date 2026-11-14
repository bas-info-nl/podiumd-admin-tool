"""SqlSessionStore: refreshing, ending and finding Sessions (tasks 7.3 to 7.6, design D2).

Requests save a Session after a refresh or a touch; sign-out, back-channel
logout and the expiry sweep remove it, which also purges its tokens. The
back-channel logout finds Sessions by ``sid`` and the sweep finds expired
ones, both without knowing the session identifier: they get an opaque ref.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.session_crypto import TokenCipher
from podiumd_admin.adapters.db.sessions import SqlSessionStore
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session, SessionTokens

pytestmark = pytest.mark.integration

KEY = Fernet.generate_key().decode()
CREATED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _tokens(suffix: str = "1") -> SessionTokens:
    return SessionTokens(
        access_token=f"access-{suffix}",
        refresh_token=f"refresh-{suffix}",
        id_token=f"id-{suffix}",
        access_token_expires_at=CREATED_AT + timedelta(minutes=5),
    )


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


def _store(connection: Any) -> SqlSessionStore:
    return SqlSessionStore(connection, TokenCipher([KEY]))


async def _add(engine: AsyncEngine, *sessions: tuple[str, Session]) -> None:
    async with engine.begin() as connection:
        for session_id, session in sessions:
            await _store(connection).add(session_id, session)


async def test_save_replaces_the_session(app_engine: AsyncEngine) -> None:
    await _add(app_engine, ("session-1", _session()))
    later = _session(
        last_seen_at=CREATED_AT + timedelta(minutes=10),
        roles=frozenset(),
        username="j.jansen-de-vries",
        tokens=_tokens("2"),
    )

    async with app_engine.begin() as connection:
        saved = await _store(connection).save("session-1", later)
    async with app_engine.connect() as connection:
        found = await _store(connection).get("session-1")

    assert saved is True
    assert found == later


async def test_save_of_an_ended_session_changes_nothing(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        saved = await _store(connection).save("gone", _session())
        rows = (await connection.execute(text("SELECT count(*) FROM sessions"))).scalar()

    assert saved is False
    assert rows == 0


async def test_remove_deletes_the_row_with_its_tokens(app_engine: AsyncEngine) -> None:
    await _add(app_engine, ("session-1", _session()), ("session-2", _session()))

    async with app_engine.begin() as connection:
        first = await _store(connection).remove("session-1")
        again = await _store(connection).remove("session-1")
    async with app_engine.connect() as connection:
        rows = (await connection.execute(text("SELECT count(*) FROM sessions"))).scalar()

    assert (first, again, rows) == (True, False, 1)


async def test_remove_of_a_blank_id_removes_nothing(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        assert await _store(connection).remove("") is False


async def test_sessions_are_found_by_keycloak_session_id_and_removed_by_ref(
    app_engine: AsyncEngine,
) -> None:
    await _add(
        app_engine,
        ("session-1", _session()),
        ("session-2", _session(keycloak_session_id="kc-sid-1")),
        ("session-3", _session(keycloak_session_id="kc-sid-2")),
    )

    async with app_engine.begin() as connection:
        found = await _store(connection).find_by_keycloak_session_id("kc-sid-1")
        removed = [await _store(connection).remove_by_ref(item.ref) for item in found]
        removed_again = await _store(connection).remove_by_ref(found[0].ref)
    async with app_engine.connect() as connection:
        remaining = await _store(connection).get("session-3")

    assert len(found) == 2
    assert {item.session.keycloak_session_id for item in found} == {"kc-sid-1"}
    assert "session-1" not in {item.ref for item in found}
    assert removed == [True, True]
    assert removed_again is False
    assert remaining is not None


@pytest.mark.parametrize("ref", ["", "not-hex", "00"])
async def test_a_malformed_ref_removes_nothing(app_engine: AsyncEngine, ref: str) -> None:
    await _add(app_engine, ("session-1", _session()))

    async with app_engine.begin() as connection:
        assert await _store(connection).remove_by_ref(ref) is False


async def test_expired_sessions_are_found_idle_or_past_their_lifetime(
    app_engine: AsyncEngine,
) -> None:
    now = CREATED_AT + timedelta(hours=8)
    await _add(
        app_engine,
        (
            "idle",
            _session(last_seen_at=now - timedelta(minutes=31), expires_at=now + timedelta(hours=1)),
        ),
        (
            "active",
            _session(last_seen_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1)),
        ),
        ("past-lifetime", _session(last_seen_at=now - timedelta(minutes=1), expires_at=now)),
    )

    async with app_engine.connect() as connection:
        found = await _store(connection).find_expired(
            last_seen_until=now - timedelta(minutes=30), now=now, limit=10
        )
        limited = await _store(connection).find_expired(
            last_seen_until=now - timedelta(minutes=30), now=now, limit=1
        )

    assert sorted(item.session.last_seen_at for item in found) == [
        now - timedelta(minutes=31),
        now - timedelta(minutes=1),
    ]
    assert len(limited) == 1


async def test_an_expired_session_with_unreadable_tokens_is_still_found(
    app_engine: AsyncEngine,
) -> None:
    """A rotated-out key must not hide a session from the sweep, or it never expires."""
    async with app_engine.begin() as connection:
        await SqlSessionStore(connection, TokenCipher([Fernet.generate_key().decode()])).add(
            "old-key", _session(last_seen_at=CREATED_AT)
        )

    async with app_engine.begin() as connection:
        found = await _store(connection).find_expired(
            last_seen_until=CREATED_AT + timedelta(hours=1), now=CREATED_AT, limit=10
        )
        removed = await _store(connection).remove_by_ref(found[0].ref)

    assert len(found) == 1
    assert found[0].session.tokens is None
    assert removed is True


async def test_an_expired_session_is_removed_only_while_it_is_still_expired(
    app_engine: AsyncEngine,
) -> None:
    now = CREATED_AT + timedelta(hours=1)
    idle_since = now - timedelta(minutes=30)
    await _add(
        app_engine,
        ("idle", _session()),
        ("idle-exactly", _session(last_seen_at=idle_since)),
        ("past-lifetime", _session(last_seen_at=now, expires_at=now)),
        ("active", _session(last_seen_at=now)),
    )

    async with app_engine.begin() as connection:
        store = _store(connection)
        [past_lifetime] = [
            item
            for item in await store.find_expired(last_seen_until=idle_since, now=now, limit=10)
            if item.session.expires_at == now
        ]
        removed = (
            await store.remove_expired("idle", last_seen_until=idle_since, now=now),
            await store.remove_expired("idle-exactly", last_seen_until=idle_since, now=now),
            await store.remove_expired_by_ref(
                past_lifetime.ref, last_seen_until=idle_since, now=now
            ),
            await store.remove_expired("active", last_seen_until=idle_since, now=now),
            await store.remove_expired("", last_seen_until=idle_since, now=now),
            await store.remove_expired_by_ref("not-hex", last_seen_until=idle_since, now=now),
        )
    async with app_engine.connect() as connection:
        remaining = await _store(connection).get("active")

    assert removed == (True, True, True, False, False, False)
    assert remaining is not None


async def test_a_session_touched_after_the_sweep_found_it_is_not_removed(
    app_engine: AsyncEngine,
) -> None:
    """A request saves its touch between the sweep's read and its removal."""
    now = CREATED_AT + timedelta(hours=1)
    idle_since = now - timedelta(minutes=30)
    await _add(app_engine, ("session-1", _session()))

    async with app_engine.connect() as connection:
        [stale] = await _store(connection).find_expired(
            last_seen_until=idle_since, now=now, limit=10
        )
    touched = _session(last_seen_at=now)
    async with app_engine.begin() as connection:
        assert await _store(connection).save("session-1", touched) is True
    async with app_engine.begin() as connection:
        removed = await _store(connection).remove_expired_by_ref(
            stale.ref, last_seen_until=idle_since, now=now
        )
    async with app_engine.connect() as connection:
        found = await _store(connection).get("session-1")

    assert removed is False
    assert found == touched


async def test_a_removal_waits_for_a_concurrent_touch_and_then_keeps_the_session(
    app_engine: AsyncEngine,
) -> None:
    """The DELETE meets the row while a request is touching it, and re-checks it after."""
    now = CREATED_AT + timedelta(hours=1)
    idle_since = now - timedelta(minutes=30)
    await _add(app_engine, ("session-1", _session()))
    [stale] = await _find_expired(app_engine, idle_since, now)

    async with app_engine.connect() as touching:
        await touching.begin()
        assert await _store(touching).save("session-1", _session(last_seen_at=now)) is True

        async def sweep() -> bool:
            async with app_engine.begin() as connection:
                return await _store(connection).remove_expired_by_ref(
                    stale.ref, last_seen_until=idle_since, now=now
                )

        removal = asyncio.create_task(sweep())
        await asyncio.sleep(0.5)
        assert not removal.done(), "the DELETE should wait for the uncommitted touch"
        await touching.commit()
        removed = await asyncio.wait_for(removal, timeout=10)

    assert removed is False
    assert await _find_expired(app_engine, idle_since, now) == []


async def _find_expired(engine: AsyncEngine, idle_since: datetime, now: datetime) -> list[Any]:
    async with engine.connect() as connection:
        return await _store(connection).find_expired(last_seen_until=idle_since, now=now, limit=10)
