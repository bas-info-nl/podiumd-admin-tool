"""Ports for the Audit Log: where Audit Entries are stored and what goes to stdout.

Design D1 and D4. The database adapter implements ``AuditRepository``; the
structlog adapter implements ``AuditSink`` and writes JSON lines with
``log_type: "audit"`` to stdout.
"""

from __future__ import annotations

from typing import Protocol

from podiumd_admin.domain.audit import AuditEntry, UnauthenticatedFailureSummary


class AuditRepository(Protocol):
    """Stores Audit Entries. Append-only: there is no way to change or delete one."""

    async def add(self, entry: AuditEntry) -> None:
        """Insert ``entry``. Raises if it could not be stored."""
        ...


class AuditSink(Protocol):
    """Writes audit events to stdout, never to the database."""

    def audit_write_failed(self, entry: AuditEntry, error: Exception) -> None:
        """Report that ``entry`` could not be stored because of ``error``."""
        ...

    def unauthenticated_failures(self, summary: UnauthenticatedFailureSummary) -> None:
        """Write one combined line for identical unauthenticated failures."""
        ...
