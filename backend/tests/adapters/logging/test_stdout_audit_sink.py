"""StdoutAuditSink and the structlog configuration (task 5.1).

Spec: audit-log, "Structured copy on stdout", "Recording unauthenticated
failures" and "No action without an Audit Entry". Design D4: every audit line
is one JSON object with ``log_type: "audit"``; ordinary application log lines
never carry that marker.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog

from podiumd_admin.adapters.logging import (
    AUDIT_LOG_TYPE,
    StdoutAuditSink,
    configure_logging,
)
from podiumd_admin.domain.audit import (
    AuditEntry,
    Outcome,
    ReasonCode,
    UnauthenticatedFailureSummary,
)
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.ports.audit import AuditSink

OCCURRED_AT = datetime(2026, 11, 8, 14, 30, 15, 123456, tzinfo=UTC)
ENVIRONMENT = EnvironmentIdentity(municipality="Utrecht", stage=Stage.ACCP, label="Hosting B.V.")


def _entry(**overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": OCCURRED_AT,
        "environment": ENVIRONMENT,
        "action": "script-run:start",
        "outcome": Outcome.DENIED,
        "reason": ReasonCode.MISSING_PERMISSION,
        "user_subject": "f3b2c1d0-0000-4000-8000-000000000001",
        "username": "j.jansen",
        "target": "openzaak/reindex",
        "parameters": {"script": "reindex", "batch": 500, "dry_run": True, "note": None},
        "correlation_id": "corr-1",
        "client_ip": "2001:db8::1",
    }
    fields.update(overrides)
    return AuditEntry(**fields)


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    """Every line written, parsed as JSON; fails if one is not a JSON object."""
    text = stream.getvalue()
    assert text == "" or text.endswith("\n")
    lines = [json.loads(line) for line in text.splitlines()]
    assert all(isinstance(line, dict) for line in lines)
    return lines


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """configure_logging changes global state; put it back after every test."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    structlog.reset_defaults()
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def sink(stream: io.StringIO) -> StdoutAuditSink:
    return StdoutAuditSink(stream=stream)


def test_the_sink_satisfies_the_port(sink: StdoutAuditSink) -> None:
    # Checked by mypy: StdoutAuditSink is a structurally valid AuditSink.
    typed: AuditSink = sink

    assert typed is sink


# --- Stored Audit Entries ------------------------------------------------------


def test_a_stored_entry_is_one_json_line_with_every_field(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    entry = _entry()

    sink.entry_stored(entry)

    assert _lines(stream) == [
        {
            "log_type": "audit",
            "event": "audit_entry_stored",
            "id": str(entry.id),
            "occurred_at": "2026-11-08T14:30:15.123456+00:00",
            "environment_municipality": "Utrecht",
            "environment_stage": "accp",
            "environment_label": "Hosting B.V.",
            "action": "script-run:start",
            "target": "openzaak/reindex",
            "outcome": "denied",
            "reason": "missing-permission",
            "user_subject": "f3b2c1d0-0000-4000-8000-000000000001",
            "username": "j.jansen",
            "parameters": {"script": "reindex", "batch": 500, "dry_run": True, "note": None},
            "correlation_id": "corr-1",
            "client_ip": "2001:db8::1",
        }
    ]


def test_optional_fields_of_a_stored_entry_are_null(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    entry = AuditEntry(
        occurred_at=OCCURRED_AT,
        environment=EnvironmentIdentity(municipality="Utrecht", stage=Stage.PROD),
        action="sign-in",
        outcome=Outcome.ALLOWED,
        correlation_id="corr-2",
    )

    sink.entry_stored(entry)

    [line] = _lines(stream)
    assert uuid.UUID(line["id"]) == entry.id
    assert line["environment_label"] is None
    assert line["reason"] is None
    assert line["username"] is None
    assert line["client_ip"] is None
    assert line["parameters"] == {}


def test_a_line_with_line_breaks_in_its_values_stays_one_line(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    sink.entry_stored(_entry(target="line one\nline two\r\n", parameters={"note": "a\nb"}))

    [line] = _lines(stream)
    assert line["parameters"] == {"note": "a\nb"}


def test_each_stored_entry_is_its_own_line(sink: StdoutAuditSink, stream: io.StringIO) -> None:
    first, second = _entry(), _entry()

    sink.entry_stored(first)
    sink.entry_stored(second)

    assert [line["id"] for line in _lines(stream)] == [str(first.id), str(second.id)]


def test_the_sink_writes_to_stdout_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    entry = _entry()

    StdoutAuditSink().entry_stored(entry)

    [line] = [json.loads(text) for text in capsys.readouterr().out.splitlines()]
    assert line["log_type"] == "audit"
    assert line["id"] == str(entry.id)


def test_audit_lines_are_written_whatever_the_log_level(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    # Raising the level for ordinary logs must never drop an audit line.
    configure_logging(stream=io.StringIO(), level=logging.CRITICAL)

    sink.entry_stored(_entry())

    assert len(_lines(stream)) == 1


# --- Failed audit writes -------------------------------------------------------


def test_a_failed_audit_write_is_one_line_with_the_entry_and_the_error_type(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    entry = _entry()
    secret = "password=hunter2"  # noqa: S105 - a fake secret, to prove it is not written

    sink.audit_write_failed(entry, ConnectionError(f"could not connect: {secret}"))

    [line] = _lines(stream)
    assert line["log_type"] == "audit"
    assert line["event"] == "audit_write_failed"
    assert line["id"] == str(entry.id)
    assert line["action"] == "script-run:start"
    assert line["outcome"] == "denied"
    assert line["error_type"] == "builtins.ConnectionError"
    assert "hunter2" not in stream.getvalue()


# --- Unauthenticated failures --------------------------------------------------


def test_unauthenticated_failures_are_one_combined_line_with_a_count(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    summary = UnauthenticatedFailureSummary(
        client_ip="192.0.2.10",
        reason=ReasonCode.INVALID_STATE,
        count=500,
        first_at=OCCURRED_AT,
        last_at=datetime(2026, 11, 8, 14, 31, 10, tzinfo=UTC),
    )

    sink.unauthenticated_failures(summary)

    assert _lines(stream) == [
        {
            "log_type": "audit",
            "event": "unauthenticated_failures",
            "client_ip": "192.0.2.10",
            "reason": "invalid-state",
            "count": 500,
            "first_at": "2026-11-08T14:30:15.123456+00:00",
            "last_at": "2026-11-08T14:31:10+00:00",
        }
    ]


def test_the_overflow_line_has_no_client_ip(sink: StdoutAuditSink, stream: io.StringIO) -> None:
    summary = UnauthenticatedFailureSummary(
        client_ip=None,
        reason=ReasonCode.NO_SESSION,
        count=3,
        first_at=OCCURRED_AT,
        last_at=OCCURRED_AT,
    )

    sink.unauthenticated_failures(summary)

    [line] = _lines(stream)
    assert line["client_ip"] is None
    assert line["reason"] == "no-session"


# --- Ordinary application logs -------------------------------------------------


def test_ordinary_structlog_lines_are_json_without_the_audit_marker(stream: io.StringIO) -> None:
    configure_logging(stream=stream)

    structlog.get_logger("podiumd_admin.test").info("environment_loaded", municipality="Utrecht")

    [line] = _lines(stream)
    assert line["event"] == "environment_loaded"
    assert line["municipality"] == "Utrecht"
    assert line["level"] == "info"
    assert "timestamp" in line
    assert line["log_type"] != AUDIT_LOG_TYPE


def test_an_ordinary_log_call_cannot_spoof_the_audit_marker(stream: io.StringIO) -> None:
    configure_logging(stream=stream)
    logger = structlog.get_logger("podiumd_admin.test")

    logger.info("spoofed", log_type="audit")
    logger.bind(log_type="audit").warning("bound")
    structlog.contextvars.bind_contextvars(log_type="audit")
    try:
        logger.error("from_context")
    finally:
        structlog.contextvars.clear_contextvars()

    lines = _lines(stream)
    assert [line["event"] for line in lines] == ["spoofed", "bound", "from_context"]
    assert all(line["log_type"] != AUDIT_LOG_TYPE for line in lines)


def test_stdlib_logging_is_json_without_the_audit_marker(stream: io.StringIO) -> None:
    configure_logging(stream=stream)

    logging.getLogger("uvicorn.error").warning("worker %s started", 1, extra={"log_type": "audit"})

    [line] = _lines(stream)
    assert line["event"] == "worker 1 started"
    assert line["level"] == "warning"
    assert line["logger"] == "uvicorn.error"
    assert line["log_type"] != AUDIT_LOG_TYPE


def test_exceptions_in_ordinary_logs_stay_on_one_line(stream: io.StringIO) -> None:
    configure_logging(stream=stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger("podiumd_admin.test").exception("failed")

    [line] = _lines(stream)
    assert "RuntimeError" in line["exception"]


def test_the_log_level_filters_ordinary_logs(stream: io.StringIO) -> None:
    configure_logging(stream=stream, level=logging.WARNING)
    logger = structlog.get_logger("podiumd_admin.test")

    logger.info("hidden")
    logging.getLogger("sqlalchemy").info("hidden too")
    logger.warning("shown")

    assert [line["event"] for line in _lines(stream)] == ["shown"]


def test_the_log_level_filters_a_child_logger_with_its_own_level(stream: io.StringIO) -> None:
    # uvicorn sets its own loggers to INFO; their records propagate to the
    # root handler whatever the root level, so the handler must filter too.
    child = logging.getLogger("podiumd_admin.test.own_level")
    child_level = child.level
    child.setLevel(logging.INFO)
    try:
        configure_logging(stream=stream, level=logging.WARNING)

        child.info("hidden")
        child.warning("shown")
    finally:
        child.setLevel(child_level)

    assert [line["event"] for line in _lines(stream)] == ["shown"]


def test_audit_lines_are_written_at_a_warning_threshold(
    sink: StdoutAuditSink, stream: io.StringIO
) -> None:
    configure_logging(stream=io.StringIO(), level=logging.WARNING)

    sink.entry_stored(_entry())

    assert len(_lines(stream)) == 1
