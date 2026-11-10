"""The structlog stdout Audit Log sink (design D4).

Spec: audit-log, "Structured copy on stdout", "Recording unauthenticated
failures" and "No action without an Audit Entry". Every line is one JSON
object with ``log_type: "audit"``:

- ``audit_entry_stored``: the copy of a stored Audit Entry, with the same
  fields. The caller writes it only after the commit (see
  ``adapters.db.unit_of_work``), so stdout never shows an entry that was not
  stored;
- ``audit_write_failed``: an Audit Entry that could not be stored, with the
  type of the error. The error message is left out, because it could hold
  secrets, such as a connection string;
- ``unauthenticated_failures``: the combined line for identical
  unauthenticated failures, with a count.

The sink has its own structlog pipeline, separate from ``configure_logging``,
so the log level never drops an audit line and ordinary logging cannot change
how an audit line looks.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from typing import Any, Final, TextIO

import structlog
from structlog.typing import EventDict, WrappedLogger

from podiumd_admin.adapters.audit_fields import audit_entry_fields
from podiumd_admin.domain.audit import AuditEntry, UnauthenticatedFailureSummary

AUDIT_LOG_TYPE: Final = "audit"


def _json_default(value: object) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} cannot be written to an audit line")


def _mark_audit(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Put the marker and the event first, so the line reads well."""
    event = event_dict.pop("event")
    return {"log_type": AUDIT_LOG_TYPE, "event": event, **event_dict}


class StdoutAuditSink:
    """Implements ``AuditSink``: writes audit lines to stdout as JSON.

    Thread-safe: structlog's ``WriteLogger`` writes each line under a lock.
    """

    def __init__(self, *, stream: TextIO | None = None) -> None:
        self._logger: Any = structlog.wrap_logger(
            structlog.WriteLogger(stream if stream is not None else sys.stdout),
            processors=[_mark_audit, structlog.processors.JSONRenderer(default=_json_default)],
            # Set explicitly, so structlog.configure() cannot change the audit lines.
            wrapper_class=structlog.BoundLogger,
            context_class=dict,
        )

    def entry_stored(self, entry: AuditEntry) -> None:
        """Write the copy of ``entry``. Call only once it has been committed."""
        self._logger.msg("audit_entry_stored", **audit_entry_fields(entry))

    def audit_write_failed(self, entry: AuditEntry, error: Exception) -> None:
        """Report that ``entry`` could not be stored, with the type of ``error``."""
        error_type = type(error)
        self._logger.msg(
            "audit_write_failed",
            **audit_entry_fields(entry),
            error_type=f"{error_type.__module__}.{error_type.__qualname__}",
        )

    def unauthenticated_failures(self, summary: UnauthenticatedFailureSummary) -> None:
        """Write one combined line for identical unauthenticated failures."""
        self._logger.msg(
            "unauthenticated_failures",
            client_ip=summary.client_ip,
            reason=summary.reason.value,
            count=summary.count,
            first_at=summary.first_at,
            last_at=summary.last_at,
        )
