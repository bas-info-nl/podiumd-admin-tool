"""One database transaction whose stored Audit Entries reach stdout only after commit.

Spec: audit-log, "Structured copy on stdout". Design D4: the JSON line with
``log_type: "audit"`` is written after the commit, so stdout never shows an
Audit Entry that was not stored.

``audited_transaction`` opens a transaction and hands out an
``AuditRepository`` that remembers each entry it inserted. Once the
transaction has committed, it writes those entries to the ``AuditSink``, in
order and once each. On a rollback or a failed commit nothing is written.

If any statement fails, PostgreSQL aborts the whole transaction, so none of
its entries can be committed, even when the caller swallows the error (as
``AuditRecorder.record_denial`` does for a failed insert). The commit then
raises nothing but rolls back. So before the commit the hook reads the
transaction status from the driver, and writes nothing for an aborted
transaction. Savepoints are not supported: an entry inserted under a
savepoint that is later rolled back would still be written.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from psycopg.pq import TransactionStatus
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from podiumd_admin.adapters.db.audit import SqlAuditRepository
from podiumd_admin.domain.audit import AuditEntry
from podiumd_admin.ports.audit import AuditRepository, AuditSink


@dataclass
class _RememberingAuditRepository:
    """Inserts through ``SqlAuditRepository`` and remembers what it inserted."""

    repository: SqlAuditRepository
    inserted: list[AuditEntry] = field(default_factory=list)

    async def add(self, entry: AuditEntry) -> None:
        await self.repository.add(entry)
        self.inserted.append(entry)


async def _is_aborted(connection: AsyncConnection) -> bool:
    """Whether a failed statement has aborted the open transaction."""
    raw = await connection.get_raw_connection()
    driver_connection = raw.driver_connection
    if driver_connection is None:  # pragma: no cover - a checked-out connection always has one
        return True
    status: TransactionStatus = driver_connection.info.transaction_status
    return status == TransactionStatus.INERROR


@dataclass(frozen=True, slots=True)
class AuditedTransaction:
    """The connection of an open transaction, and the Audit Log to record in it."""

    connection: AsyncConnection
    audit_repository: AuditRepository


@contextlib.asynccontextmanager
async def audited_transaction(
    engine: AsyncEngine, sink: AuditSink
) -> AsyncIterator[AuditedTransaction]:
    """Run a transaction; write its Audit Entries to ``sink`` once it has committed.

    The transaction commits when the block ends normally and rolls back when
    it raises. A failing stdout copy does not raise: the entry and the action
    it records have been committed, and reporting a failure would be false.
    The other entries are still written.
    """
    async with engine.begin() as connection:
        repository = _RememberingAuditRepository(SqlAuditRepository(connection))
        yield AuditedTransaction(connection=connection, audit_repository=repository)
        # The commit of an aborted transaction raises nothing but rolls back.
        aborted = await _is_aborted(connection)
    if aborted:
        return
    for entry in repository.inserted:
        with contextlib.suppress(Exception):
            sink.entry_stored(entry)
