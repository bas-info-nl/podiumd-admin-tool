"""Write-first auditing: no action without an Audit Entry.

Spec: audit-log, "No action without an Audit Entry". Design D4: an allowed
action runs only after its Audit Entry has been inserted. If the insert fails
the action does not run and the caller learns the action could not be
recorded. A denial is refused even when its entry cannot be stored; the
failure is then written to stdout through the AuditSink.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from podiumd_admin.application.audit import AuditRecorder, AuditWriteFailedError
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.ports.audit import AuditRepository, AuditSink
from tests.application.fakes import FakeAuditRepository, FakeAuditSink

ENVIRONMENT = EnvironmentIdentity(municipality="Utrecht", stage=Stage.ACCP)


def _entry(outcome: Outcome = Outcome.ALLOWED, **overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": datetime(2026, 11, 8, 9, 30, tzinfo=UTC),
        "environment": ENVIRONMENT,
        "action": "sign-out",
        "outcome": outcome,
        "correlation_id": "c-1",
        "client_ip": "192.0.2.10",
        "user_subject": "f3b2c1d0",
        "username": "j.jansen",
    }
    if outcome is Outcome.DENIED:
        fields["reason"] = ReasonCode.MISSING_PERMISSION
    fields.update(overrides)
    return AuditEntry(**fields)


@pytest.fixture
def repository() -> FakeAuditRepository:
    return FakeAuditRepository()


@pytest.fixture
def sink() -> FakeAuditSink:
    return FakeAuditSink()


@pytest.fixture
def recorder(repository: FakeAuditRepository, sink: FakeAuditSink) -> AuditRecorder:
    return AuditRecorder(repository=repository, sink=sink)


def test_fakes_satisfy_the_ports(repository: FakeAuditRepository, sink: FakeAuditSink) -> None:
    # Checked by mypy: the fakes are structurally valid implementations.
    typed_repository: AuditRepository = repository
    typed_sink: AuditSink = sink

    assert typed_repository is repository
    assert typed_sink is sink


# --- record_then_act ------------------------------------------------------------


async def test_action_runs_after_its_entry_is_inserted(
    recorder: AuditRecorder, repository: FakeAuditRepository
) -> None:
    entry = _entry()

    async def end_session() -> str:
        repository.events.append("act")
        return "ended"

    result = await recorder.record_then_act(entry, end_session)

    assert result == "ended"
    assert repository.events == ["insert", "act"]
    assert repository.entries == [entry]


async def test_insert_failure_prevents_the_action(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    insert_error = PermissionError("permission denied for table audit_entries")
    repository.error = insert_error
    entry = _entry()
    acted = False

    async def end_session() -> None:
        nonlocal acted
        acted = True

    with pytest.raises(AuditWriteFailedError) as raised:
        await recorder.record_then_act(entry, end_session)

    assert not acted
    assert raised.value.entry is entry
    assert raised.value.__cause__ is insert_error
    assert "could not be recorded" in str(raised.value)
    assert sink.write_failures == [(entry, insert_error)]


async def test_insert_failure_raises_audit_write_failed_even_when_the_stdout_report_fails(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    # Issue #13: a failing stdout report must not mask the promised error.
    insert_error = PermissionError("permission denied for table audit_entries")
    repository.error = insert_error
    sink.report_error = OSError("stdout closed")
    entry = _entry()

    async def act() -> None:
        pytest.fail("the action must not run")

    with pytest.raises(AuditWriteFailedError) as raised:
        await recorder.record_then_act(entry, act)

    assert raised.value.__cause__ is insert_error
    assert sink.write_failures == [(entry, insert_error)]


async def test_an_action_that_fails_keeps_its_entry_and_raises_unchanged(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    async def fail() -> None:
        raise RuntimeError("Kubernetes API unavailable")

    with pytest.raises(RuntimeError, match="Kubernetes API unavailable"):
        await recorder.record_then_act(_entry(), fail)

    assert len(repository.entries) == 1
    assert sink.write_failures == []


async def test_cancellation_during_the_insert_is_not_reported_as_an_audit_failure(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    repository.error = asyncio.CancelledError()

    async def act() -> None:
        pytest.fail("the action must not run")

    with pytest.raises(asyncio.CancelledError):
        await recorder.record_then_act(_entry(), act)

    assert sink.write_failures == []


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (Outcome.DENIED, ReasonCode.MISSING_PERMISSION),
        (Outcome.SUCCEEDED, None),
        (Outcome.FAILED, None),
        (Outcome.INFO, ReasonCode.IDLE),
    ],
    ids=str,
)
async def test_record_then_act_takes_only_allowed_entries(
    recorder: AuditRecorder,
    repository: FakeAuditRepository,
    outcome: Outcome,
    reason: ReasonCode | None,
) -> None:
    async def act() -> None:
        pytest.fail("the action must not run")

    with pytest.raises(ValueError, match="allowed"):
        await recorder.record_then_act(_entry(outcome, reason=reason), act)

    assert repository.events == []


# --- record_denial ----------------------------------------------------------------


async def test_denial_is_recorded(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    entry = _entry(Outcome.DENIED)

    await recorder.record_denial(entry)

    assert repository.entries == [entry]
    assert sink.write_failures == []


async def test_denial_still_denies_when_the_insert_fails_and_reports_it_on_stdout(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    insert_error = ConnectionError("database unreachable")
    repository.error = insert_error
    entry = _entry(Outcome.DENIED)

    # No exception: the caller goes on to refuse the request.
    await recorder.record_denial(entry)

    assert repository.entries == []
    assert sink.write_failures == [(entry, insert_error)]


async def test_denial_does_not_raise_when_the_insert_and_the_stdout_report_both_fail(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    # Issue #13: record_denial never raises, so the request is refused as a denial.
    insert_error = ConnectionError("database unreachable")
    repository.error = insert_error
    sink.report_error = OSError("stdout closed")
    entry = _entry(Outcome.DENIED)

    await recorder.record_denial(entry)

    assert sink.write_failures == [(entry, insert_error)]


async def test_cancellation_during_a_denial_insert_propagates(
    recorder: AuditRecorder, repository: FakeAuditRepository, sink: FakeAuditSink
) -> None:
    repository.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await recorder.record_denial(_entry(Outcome.DENIED))

    assert sink.write_failures == []


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [(Outcome.ALLOWED, None), (Outcome.INFO, ReasonCode.IDLE)],
    ids=str,
)
async def test_record_denial_takes_only_denied_entries(
    recorder: AuditRecorder,
    repository: FakeAuditRepository,
    outcome: Outcome,
    reason: ReasonCode | None,
) -> None:
    with pytest.raises(ValueError, match="denied"):
        await recorder.record_denial(_entry(outcome, reason=reason))

    assert repository.events == []
