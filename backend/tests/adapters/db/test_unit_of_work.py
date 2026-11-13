"""SqlUnitOfWork: the UnitOfWork port over ``audited_transaction`` (design D4).

One transaction over the Audit Log, sessions and sign-in attempts. Stored
Audit Entries reach stdout only after the commit; a transaction aborted by a
swallowed failure raises ``TransactionAbortedError`` (issue #30).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.session_crypto import TokenCipher
from podiumd_admin.adapters.db.unit_of_work import SqlUnitOfWork, TransactionAbortedError
from podiumd_admin.application.audit import AuditRecorder
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.domain.sign_in import SignInAttempt
from podiumd_admin.ports.unit_of_work import UnitOfWork
from tests.application.fakes import FakeAuditSink

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
ENVIRONMENT = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.ACCP)


def _unit_of_work(engine: AsyncEngine, sink: FakeAuditSink) -> SqlUnitOfWork:
    return SqlUnitOfWork(engine, sink, TokenCipher([Fernet.generate_key().decode()]))


def _attempt() -> SignInAttempt:
    return SignInAttempt(
        state="s" * 43, nonce="n" * 43, code_verifier="v" * 43, return_path="/", created_at=NOW
    )


def _denied() -> AuditEntry:
    return AuditEntry(
        occurred_at=NOW,
        environment=ENVIRONMENT,
        action="sign-in",
        outcome=Outcome.DENIED,
        reason=ReasonCode.NO_ROLE,
        correlation_id="c-1",
        user_subject="f3b2c1d0",
    )


async def test_the_stores_share_one_transaction(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    unit_of_work: UnitOfWork = _unit_of_work(app_engine, sink)

    entry = _denied()
    async with unit_of_work.begin() as transaction:
        await transaction.sign_in_attempts.add("attempt-1", _attempt())
        await transaction.audit_repository.add(entry)
        assert await transaction.sessions.get("unknown") is None

    async with app_engine.connect() as connection:
        attempts = (
            await connection.execute(text("SELECT count(*) FROM sign_in_attempts"))
        ).scalar()
        entries = (await connection.execute(text("SELECT count(*) FROM audit_entries"))).scalar()
    assert (attempts, entries) == (1, 1)
    assert sink.stored == [entry]


async def test_a_block_that_raises_rolls_everything_back(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()

    async def failing_block() -> None:
        async with _unit_of_work(app_engine, sink).begin() as transaction:
            await transaction.sign_in_attempts.add("attempt-1", _attempt())
            await transaction.audit_repository.add(_denied())
            raise LookupError

    with pytest.raises(LookupError):
        await failing_block()

    async with app_engine.connect() as connection:
        attempts = (
            await connection.execute(text("SELECT count(*) FROM sign_in_attempts"))
        ).scalar()
    assert attempts == 0
    assert sink.stored == []


async def test_a_swallowed_audit_failure_aborts_the_transaction(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    unit_of_work = _unit_of_work(app_engine, sink)

    async def block_with_a_swallowed_failure() -> None:
        async with unit_of_work.begin() as transaction:
            await transaction.sign_in_attempts.add("attempt-1", _attempt())
            recorder = AuditRecorder(repository=transaction.audit_repository, sink=sink)
            # An entry the database refuses: the same id twice.
            entry = _denied()
            await recorder.record_denial(entry)
            await recorder.record_denial(entry)

    with pytest.raises(TransactionAbortedError):
        await block_with_a_swallowed_failure()

    async with app_engine.connect() as connection:
        attempts = (
            await connection.execute(text("SELECT count(*) FROM sign_in_attempts"))
        ).scalar()
    assert attempts == 0
    assert sink.stored == []
    assert len(sink.write_failures) == 1
