"""audited_transaction: the stdout copy of an Audit Entry only after commit (task 5.1).

Spec: audit-log, "Structured copy on stdout". Design D4: the JSON line with
``log_type: "audit"`` is written after the commit, so stdout never shows an
Audit Entry that was not stored. Each stored entry is written exactly once.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.audit import SqlAuditRepository
from podiumd_admin.adapters.db.unit_of_work import (
    TransactionAbortedError,
    TransactionOwnershipError,
    audited_transaction,
)
from podiumd_admin.adapters.logging import StdoutAuditSink
from podiumd_admin.application.audit import AuditRecorder
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.ports.audit import AuditRepository
from tests.application.fakes import FakeAuditSink

pytestmark = pytest.mark.integration

ENVIRONMENT = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.ACCP)


def _entry(**overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": datetime(2026, 11, 8, 14, 30, tzinfo=UTC),
        "environment": ENVIRONMENT,
        "action": "sign-out",
        "outcome": Outcome.ALLOWED,
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return AuditEntry(**fields)


async def _stored(engine: AsyncEngine, entry: AuditEntry) -> bool:
    async with engine.connect() as connection:
        return await SqlAuditRepository(connection).get(entry.id) is not None


class _ActionFailedError(Exception):
    pass


async def test_a_committed_entry_is_written_to_stdout_once_after_the_commit(
    app_engine: AsyncEngine,
) -> None:
    stream = io.StringIO()
    entry = _entry()

    async with audited_transaction(app_engine, StdoutAuditSink(stream=stream)) as transaction:
        repository: AuditRepository = transaction.audit_repository
        recorder = AuditRecorder(repository=repository, sink=StdoutAuditSink(stream=stream))

        async def act() -> None:
            await transaction.connection.execute(text("SELECT 1"))

        await recorder.record_then_act(entry, act)
        # Inserted, but not committed yet: nothing on stdout.
        assert stream.getvalue() == ""

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [
        {
            "log_type": "audit",
            "event": "audit_entry_stored",
            "id": str(entry.id),
            "occurred_at": "2026-11-08T14:30:00+00:00",
            "environment_municipality": "Onsdorp",
            "environment_stage": "accp",
            "environment_label": None,
            "action": "sign-out",
            "target": None,
            "outcome": "allowed",
            "reason": None,
            "user_subject": None,
            "username": None,
            "parameters": {},
            "correlation_id": "corr-1",
            "client_ip": None,
        }
    ]
    assert await _stored(app_engine, entry)


async def test_every_entry_of_a_transaction_is_written_in_order(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    first, second = _entry(), _entry(action="session:end")

    async with audited_transaction(app_engine, sink) as transaction:
        await transaction.audit_repository.add(first)
        await transaction.audit_repository.add(second)

    assert sink.stored == [first, second]


async def test_a_rolled_back_entry_is_never_written(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    entry = _entry()

    async def fail_after_insert() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            await transaction.audit_repository.add(entry)
            raise _ActionFailedError

    with pytest.raises(_ActionFailedError):
        await fail_after_insert()

    assert sink.stored == []
    assert not await _stored(app_engine, entry)


async def test_nothing_is_written_when_the_commit_fails(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    entry = _entry()

    async def fail_at_commit() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            # A deferred constraint is checked at commit, so the commit fails.
            await transaction.connection.execute(
                text("CREATE TEMP TABLE commit_fails (id int UNIQUE DEFERRABLE INITIALLY DEFERRED)")
            )
            await transaction.connection.execute(text("INSERT INTO commit_fails VALUES (1), (1)"))
            await transaction.audit_repository.add(entry)

    with pytest.raises(IntegrityError):
        await fail_at_commit()

    assert sink.stored == []
    assert not await _stored(app_engine, entry)


async def test_an_entry_whose_insert_failed_is_not_written(app_engine: AsyncEngine) -> None:
    sink = FakeAuditSink()
    entry = _entry()

    async def insert_twice() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            await transaction.audit_repository.add(entry)
            # The same id again: the primary key refuses it.
            await transaction.audit_repository.add(entry)

    with pytest.raises(IntegrityError):
        await insert_twice()

    assert sink.stored == []


async def test_a_failing_stdout_copy_does_not_undo_the_commit_or_stop_the_others(
    app_engine: AsyncEngine,
) -> None:
    class FailingOnceSink(FakeAuditSink):
        def entry_stored(self, entry: AuditEntry) -> None:
            if not self.stored and entry.action == "sign-out":
                self.stored.append(entry)
                raise OSError("stdout closed")
            super().entry_stored(entry)

    sink = FailingOnceSink()
    first, second = _entry(), _entry(action="session:end")

    async with audited_transaction(app_engine, sink) as transaction:
        await transaction.audit_repository.add(first)
        await transaction.audit_repository.add(second)

    assert sink.stored == [first, second]
    assert await _stored(app_engine, first)
    assert await _stored(app_engine, second)


async def test_a_swallowed_insert_failure_raises_at_the_commit_and_writes_nothing(
    app_engine: AsyncEngine,
) -> None:
    # record_denial never raises, so the block ends normally although the
    # failed insert aborted the transaction and nothing was stored (issue #30).
    sink = FakeAuditSink()
    first = _entry()
    denial = _entry(outcome=Outcome.DENIED, reason=ReasonCode.MISSING_PERMISSION)

    async def deny_twice() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            recorder = AuditRecorder(repository=transaction.audit_repository, sink=sink)
            await transaction.audit_repository.add(first)
            await transaction.audit_repository.add(denial)
            await recorder.record_denial(denial)  # the same id again: refused

    with pytest.raises(TransactionAbortedError):
        await deny_twice()

    assert sink.stored == []
    assert [failed for failed, _ in sink.write_failures] == [denial]
    assert not await _stored(app_engine, first)


async def test_a_swallowed_action_failure_raises_at_the_commit_and_writes_nothing(
    app_engine: AsyncEngine,
) -> None:
    # Any failing statement aborts a PostgreSQL transaction. When the caller
    # swallows the error, the commit would roll back silently, so the action
    # and its entry were never stored. The caller must learn that (issue #30).
    sink = FakeAuditSink()
    entry = _entry()

    async def swallow_failure() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            await transaction.audit_repository.add(entry)
            with pytest.raises(DBAPIError):
                await transaction.connection.execute(text("SELECT 1/0"))

    with pytest.raises(TransactionAbortedError, match="rolled back"):
        await swallow_failure()

    assert sink.stored == []
    assert not await _stored(app_engine, entry)


async def test_rolling_back_the_owned_transaction_inside_the_block_is_a_programming_error(
    app_engine: AsyncEngine,
) -> None:
    # After an explicit rollback the driver reports IDLE, not INERROR, so the
    # abort check alone would write an entry that was never stored.
    sink = FakeAuditSink()
    entry = _entry()

    async def roll_back_inside() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            await transaction.audit_repository.add(entry)
            await transaction.connection.rollback()

    with pytest.raises(TransactionOwnershipError, match="owns the transaction") as raised:
        await roll_back_inside()

    # Not "the action could not be recorded": misuse is a programming error.
    assert not isinstance(raised.value, TransactionAbortedError)
    assert sink.stored == []
    assert not await _stored(app_engine, entry)


async def test_committing_the_owned_transaction_inside_the_block_is_a_programming_error(
    app_engine: AsyncEngine,
) -> None:
    # The block committed, so its entry IS stored. Reporting "nothing was
    # stored" (TransactionAbortedError) would be false, so the misuse gets its
    # own error. No stdout copy is written for the entry.
    sink = FakeAuditSink()
    entry = _entry()

    async def commit_inside() -> None:
        async with audited_transaction(app_engine, sink) as transaction:
            await transaction.audit_repository.add(entry)
            await transaction.connection.commit()

    with pytest.raises(TransactionOwnershipError, match="owns the transaction") as raised:
        await commit_inside()

    assert not isinstance(raised.value, TransactionAbortedError)
    assert sink.stored == []
    assert await _stored(app_engine, entry)
