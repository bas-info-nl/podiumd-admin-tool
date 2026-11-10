"""SqlAuditRepository: storing Audit Entries and reading them back (task 4.2).

Spec: audit-log, "What is recorded" and "Audit Entries are append-only".
Every test talks to PostgreSQL as ``podiumd_admin_app``, the role the
application runs with, so the append-only guarantee is the real one: the
database refuses UPDATE, DELETE and TRUNCATE on Audit Entries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.audit import SqlAuditRepository
from podiumd_admin.adapters.db.tables import STORED_REASONS
from podiumd_admin.domain.audit import (
    MAX_PARAMETER_KEY_LENGTH,
    MAX_PARAMETER_VALUE_LENGTH,
    AuditEntry,
    Outcome,
    ReasonCode,
)
from podiumd_admin.domain.audit_log import AuditLogQuery
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.ports.audit import AuditLogReader, AuditRepository

pytestmark = pytest.mark.integration

OCCURRED_AT = datetime(2026, 11, 8, 14, 30, 15, 123456, tzinfo=UTC)
ENVIRONMENT = EnvironmentIdentity(municipality="Utrecht", stage=Stage.ACCP, label="Hosting B.V.")


def _entry(**overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": OCCURRED_AT,
        "environment": ENVIRONMENT,
        "action": "sign-in",
        "outcome": Outcome.ALLOWED,
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return AuditEntry(**fields)


async def _add(engine: AsyncEngine, *entries: AuditEntry) -> None:
    async with engine.begin() as connection:
        repository: AuditRepository = SqlAuditRepository(connection)
        for entry in entries:
            await repository.add(entry)


async def _get(engine: AsyncEngine, entry_id: uuid.UUID) -> AuditEntry | None:
    async with engine.connect() as connection:
        reader: AuditLogReader = SqlAuditRepository(connection)
        return await reader.get(entry_id)


async def test_a_stored_entry_reads_back_with_every_field(app_engine: AsyncEngine) -> None:
    entry = _entry(
        action="script-run:start",
        outcome=Outcome.DENIED,
        reason=ReasonCode.MISSING_PERMISSION,
        user_subject="f3b2c1d0-0000-4000-8000-000000000001",
        username="j.jansen",
        target="openzaak/reindex",
        parameters={"script": "reindex", "batch": 500, "dry_run": True, "note": None},
        client_ip="2001:db8::1",
    )

    await _add(app_engine, entry)

    assert await _get(app_engine, entry.id) == entry


async def test_an_entry_with_truncated_parameters_reads_back(app_engine: AsyncEngine) -> None:
    long_name = "component_" + "n" * MAX_PARAMETER_KEY_LENGTH
    entry = _entry(parameters={long_name: "v" * (MAX_PARAMETER_VALUE_LENGTH + 1)})
    (stored_name,) = entry.parameters
    assert stored_name != long_name

    await _add(app_engine, entry)

    assert await _get(app_engine, entry.id) == entry
    async with app_engine.connect() as connection:
        page = await SqlAuditRepository(connection).search(AuditLogQuery())
    assert list(page.entries) == [entry]


async def test_an_entry_without_optional_fields_reads_back(app_engine: AsyncEngine) -> None:
    entry = _entry(environment=EnvironmentIdentity(municipality="Tilburg", stage=Stage.PROD))

    await _add(app_engine, entry)

    stored = await _get(app_engine, entry.id)
    assert stored == entry
    assert stored is not None
    assert stored.environment.label is None
    assert dict(stored.parameters) == {}
    assert stored.client_ip is None


async def test_the_timestamp_reads_back_in_utc(app_engine: AsyncEngine) -> None:
    entry = _entry()

    await _add(app_engine, entry)

    stored = await _get(app_engine, entry.id)
    assert stored is not None
    assert stored.occurred_at == OCCURRED_AT
    assert stored.occurred_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("outcome", list(Outcome))
async def test_every_outcome_can_be_stored(app_engine: AsyncEngine, outcome: Outcome) -> None:
    needs_reason = outcome in (Outcome.DENIED, Outcome.INFO)
    entry = _entry(outcome=outcome, reason=ReasonCode.IDLE if needs_reason else None)

    await _add(app_engine, entry)

    assert await _get(app_engine, entry.id) == entry


@pytest.mark.parametrize("reason", STORED_REASONS)
async def test_every_reason_an_entry_may_hold_can_be_stored(
    app_engine: AsyncEngine, reason: ReasonCode
) -> None:
    entry = _entry(outcome=Outcome.DENIED, reason=reason)

    await _add(app_engine, entry)

    assert await _get(app_engine, entry.id) == entry


@pytest.mark.parametrize("stage", list(Stage))
async def test_every_stage_can_be_stored(app_engine: AsyncEngine, stage: Stage) -> None:
    entry = _entry(environment=EnvironmentIdentity(municipality="Utrecht", stage=stage))

    await _add(app_engine, entry)

    assert await _get(app_engine, entry.id) == entry


async def test_an_unknown_id_reads_back_as_none(app_engine: AsyncEngine) -> None:
    assert await _get(app_engine, uuid.uuid4()) is None


async def test_adding_runs_in_the_callers_transaction(app_engine: AsyncEngine) -> None:
    """The caller's unit of work decides (design D4): a rollback leaves no entry."""
    entry = _entry()

    async with app_engine.connect() as connection:
        await SqlAuditRepository(connection).add(entry)
        await connection.rollback()

    assert await _get(app_engine, entry.id) is None


async def test_an_entry_is_stored_only_once(app_engine: AsyncEngine) -> None:
    entry = _entry()
    await _add(app_engine, entry)

    with pytest.raises(IntegrityError):
        await _add(app_engine, entry)


# --- Append-only by privilege ---------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_entries SET outcome = 'denied', reason = 'no-role'",
        "DELETE FROM audit_entries",
        "TRUNCATE audit_entries",
    ],
)
async def test_the_app_user_cannot_change_or_delete_entries(
    app_engine: AsyncEngine, statement: str
) -> None:
    entry = _entry()
    await _add(app_engine, entry)

    with pytest.raises(ProgrammingError) as raised:
        async with app_engine.begin() as connection:
            await connection.execute(text(statement))

    assert isinstance(raised.value.orig, psycopg.errors.InsufficientPrivilege)
    assert await _get(app_engine, entry.id) == entry


# --- The database repeats the domain's rules --------------------------------------


_RAW_INSERT = text(
    "INSERT INTO audit_entries (id, occurred_at, environment_municipality,"
    " environment_stage, action, outcome, reason, parameters, correlation_id)"
    " VALUES (:id, :occurred_at, :environment_municipality, :environment_stage,"
    " :action, :outcome, :reason, CAST(:parameters AS jsonb), :correlation_id)"
)
_VALID_ROW = {
    "id": "6a1f4e0e-5d43-4f5e-9f5a-0b8e3b1e2c01",
    "occurred_at": OCCURRED_AT,
    "environment_municipality": "Utrecht",
    "environment_stage": "test",
    "action": "sign-in",
    "outcome": "allowed",
    "reason": None,
    "parameters": "{}",
    "correlation_id": "corr-1",
}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"outcome": "bogus"}, id="unknown outcome"),
        pytest.param({"outcome": "denied", "reason": "bogus"}, id="unknown reason"),
        pytest.param({"outcome": "denied", "reason": "no-session"}, id="unauthenticated reason"),
        pytest.param({"outcome": "denied"}, id="denied without a reason"),
        pytest.param({"outcome": "info"}, id="info without a reason"),
        pytest.param({"reason": "no-role"}, id="allowed with a reason"),
        pytest.param({"outcome": "succeeded", "reason": "no-role"}, id="succeeded with a reason"),
        pytest.param({"environment_stage": "dev"}, id="unknown stage"),
        pytest.param({"parameters": "[]"}, id="parameters not an object"),
    ],
)
async def test_the_database_rejects_what_the_domain_forbids(
    app_engine: AsyncEngine, overrides: dict[str, object]
) -> None:
    row = {**_VALID_ROW, **overrides}

    with pytest.raises(IntegrityError) as raised:
        async with app_engine.begin() as connection:
            await connection.execute(_RAW_INSERT, row)

    assert isinstance(raised.value.orig, psycopg.errors.CheckViolation)


async def test_the_valid_row_used_above_is_accepted(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as connection:
        await connection.execute(_RAW_INSERT, _VALID_ROW)

    assert await _get(app_engine, uuid.UUID(str(_VALID_ROW["id"]))) is not None
