"""Logging adapter: JSON logs on stdout and the structlog stdout Audit Log sink.

ADR 0008 and design D4. ``configure_logging`` makes every ordinary log line,
from structlog and from the standard library, one JSON object marked
``log_type: "app"``. ``StdoutAuditSink`` writes the audit lines, marked
``log_type: "audit"``; it is the only writer of that marker.
"""

from podiumd_admin.adapters.logging.audit import AUDIT_LOG_TYPE, StdoutAuditSink
from podiumd_admin.adapters.logging.config import ORDINARY_LOG_TYPE, configure_logging

__all__ = ["AUDIT_LOG_TYPE", "ORDINARY_LOG_TYPE", "StdoutAuditSink", "configure_logging"]
