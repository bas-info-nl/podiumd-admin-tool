"""The expiry sweep against PostgreSQL (task 7.4).

Design D2 and D4: each abandoned Session gets exactly one
``session-expired``/``info`` Audit Entry and its row, with the encrypted
tokens, is deleted, in one transaction. Two sweeps running at once still
record each expiry once: the second DELETE waits for the first and then finds
nothing to remove.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.session_crypto import TokenCipher
from podiumd_admin.adapters.db.unit_of_work import SqlUnitOfWork
from podiumd_admin.application.sessions import Sessions
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import Session
from tests.application.conftest import AUTH_SETTINGS, NOW
from tests.application.fakes import FakeAuditSink, FakeClock, FakeIdentityProvider, tokens

pytestmark = pytest.mark.integration


def _sessions(engine: AsyncEngine, clock: FakeClock, cipher: TokenCipher) -> Sessions:
    sink = FakeAuditSink()
    return Sessions(
        settings=AUTH_SETTINGS,
        identity_provider=FakeIdentityProvider(),
        unit_of_work=SqlUnitOfWork(engine, sink, cipher),
        audit_sink=sink,
        failures=UnauthenticatedFailureAggregator(sink=sink, clock=clock),
        clock=clock,
    )


async def _count(engine: AsyncEngine, sql: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(sql))).scalar_one())


async def test_two_concurrent_sweeps_record_each_expiry_once(app_engine: AsyncEngine) -> None:
    cipher = TokenCipher([Fernet.generate_key().decode()])
    clock = FakeClock(NOW)
    unit_of_work = SqlUnitOfWork(app_engine, FakeAuditSink(), cipher)
    async with unit_of_work.begin() as transaction:
        for number in range(5):
            await transaction.sessions.add(
                f"abandoned-{number}",
                Session(
                    user_subject=f"user-{number}",
                    username=None,
                    keycloak_session_id=None,
                    roles=frozenset({Role.VIEWER}),
                    created_at=NOW,
                    last_seen_at=NOW,
                    expires_at=NOW + timedelta(hours=8),
                    tokens=tokens(),
                ),
            )
    clock.advance(timedelta(minutes=31))

    results = await asyncio.gather(
        _sessions(app_engine, clock, cipher).expire_abandoned(),
        _sessions(app_engine, clock, cipher).expire_abandoned(),
    )
    again = await _sessions(app_engine, clock, cipher).expire_abandoned()

    assert sum(results) == 5
    assert again == 0
    assert await _count(app_engine, "SELECT count(*) FROM sessions") == 0
    assert (
        await _count(
            app_engine,
            "SELECT count(*) FROM audit_entries "
            "WHERE action = 'session-expired' AND outcome = 'info' AND reason = 'idle'",
        )
        == 5
    )
    assert await _count(app_engine, "SELECT count(DISTINCT user_subject) FROM audit_entries") == 5
