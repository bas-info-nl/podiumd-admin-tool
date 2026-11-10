"""One database transaction whose stored Audit Entries reach stdout only after commit.

Spec: audit-log, "Structured copy on stdout". Design D4: the JSON line with
``log_type: "audit"`` is written after the commit, so stdout never shows an
Audit Entry that was not stored.

``audited_transaction`` opens a transaction and hands out an
``AuditRepository`` that remembers each entry it inserted. Once the
transaction has committed, it writes those entries to the ``AuditSink``, in
order and once each. On a rollback or a failed commit nothing is written.

If an insert fails, PostgreSQL aborts the whole transaction, so none of its
entries can be committed, even when the caller swallows the error (as
``AuditRecorder.record_denial`` does). Nothing is written for such a
transaction. Savepoints are not supported: an entry inserted under a
savepoint that is later rolled back would still be written.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from podiumd_admin.adapters.db.audit import SqlAuditRepository
from podiumd_admin.domain.audit import AuditEntry
from podiumd_admin.ports.audit import AuditRepository, AuditSink


@dataclass
class _RememberingAuditRepository:
    """Inserts through ``SqlAuditRepository`` and remembers what it inserted."""

    repository: SqlAuditRepository
    inserted: list[AuditEntry] = field(default_factory=list)
    failed: bool = False

    async def add(self, entry: AuditEntry) -> None:
        try:
            await self.repository.add(entry)
        except Exception:
            self.failed = True
            raise
        self.inserted.append(entry)


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
    if repository.failed:
        return
    for entry in repository.inserted:
        with contextlib.suppress(Exception):
            sink.entry_stored(entry)
