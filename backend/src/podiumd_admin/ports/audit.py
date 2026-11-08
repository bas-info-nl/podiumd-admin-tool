"""Ports for the Audit Log: where Audit Entries are stored and what goes to stdout.

Design D1 and D4. The database adapter implements ``AuditRepository`` and
``AuditLogReader``; the structlog adapter implements ``AuditSink`` and writes
JSON lines with ``log_type: "audit"`` to stdout.

Writing and reading are separate ports, so code that records Audit Entries
does not depend on reading the Audit Log, and the other way round.
"""

from __future__ import annotations

from typing import Protocol

from podiumd_admin.domain.audit import AuditEntry, UnauthenticatedFailureSummary
from podiumd_admin.domain.audit_log import AuditLogPage, AuditLogQuery


class AuditRepository(Protocol):
    """Stores Audit Entries. Append-only: there is no way to change or delete one."""

    async def add(self, entry: AuditEntry) -> None:
        """Insert ``entry``. Raises if it could not be stored."""
        ...


class AuditLogReader(Protocol):
    """Reads the Audit Log, for users with ``audit-log:read``."""

    async def search(self, query: AuditLogQuery) -> AuditLogPage:
        """Return the page ``query`` asks for: matching entries, newest first."""
        ...


class AuditSink(Protocol):
    """Writes audit events to stdout, never to the database."""

    def audit_write_failed(self, entry: AuditEntry, error: Exception) -> None:
        """Report that ``entry`` could not be stored because of ``error``."""
        ...

    def unauthenticated_failures(self, summary: UnauthenticatedFailureSummary) -> None:
        """Write one combined line for identical unauthenticated failures."""
        ...
