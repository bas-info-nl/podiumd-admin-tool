"""In-memory fakes of the ports, for application-layer tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from podiumd_admin.domain.audit import AuditEntry, UnauthenticatedFailureSummary


@dataclass
class FakeAuditRepository:
    """Stores entries in a list; can be told to fail every insert."""

    events: list[str] = field(default_factory=list)
    entries: list[AuditEntry] = field(default_factory=list)
    error: Exception | BaseException | None = None

    async def add(self, entry: AuditEntry) -> None:
        self.events.append("insert")
        if self.error is not None:
            raise self.error
        self.entries.append(entry)


@dataclass
class FakeAuditSink:
    """Collects what would be written to stdout; can be told to fail the failure report."""

    write_failures: list[tuple[AuditEntry, Exception]] = field(default_factory=list)
    summaries: list[UnauthenticatedFailureSummary] = field(default_factory=list)
    report_error: Exception | None = None

    def audit_write_failed(self, entry: AuditEntry, error: Exception) -> None:
        self.write_failures.append((entry, error))
        if self.report_error is not None:
            raise self.report_error

    def unauthenticated_failures(self, summary: UnauthenticatedFailureSummary) -> None:
        self.summaries.append(summary)


@dataclass
class FakeClock:
    """A clock that only moves when a test advances it."""

    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta
