"""The Audit Log in PostgreSQL: ``AuditRepository`` and ``AuditLogReader``.

Design D4. The repository works on the caller's connection and never commits:
the caller's unit of work decides whether an Audit Entry and the action it
records commit together, or whether the entry is committed first (before an
external side effect).

The repository offers no way to change or delete an Audit Entry, and the app
role the application runs with lacks those privileges anyway.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Row, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from podiumd_admin.adapters.db.tables import audit_entries
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.audit_log import AUDIT_LOG_PAGE_SIZE, AuditLogPage, AuditLogQuery
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage

_LIKE_ESCAPE = "\\"


def _contains(value: str) -> str:
    """A LIKE pattern matching ``value`` anywhere, with its wildcards taken literally."""
    escaped = (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _conditions(query: AuditLogQuery) -> list[ColumnElement[bool]]:
    columns = audit_entries.c
    conditions: list[ColumnElement[bool]] = []
    if query.occurred_from is not None:
        conditions.append(columns.occurred_at >= query.occurred_from)
    if query.occurred_until is not None:
        conditions.append(columns.occurred_at <= query.occurred_until)
    if query.username is not None:
        conditions.append(columns.username.ilike(_contains(query.username), escape=_LIKE_ESCAPE))
    if query.action is not None:
        conditions.append(columns.action == query.action)
    if query.outcome is not None:
        conditions.append(columns.outcome == query.outcome.value)
    return conditions


def _to_row(entry: AuditEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "occurred_at": entry.occurred_at,
        "environment_municipality": entry.environment.municipality,
        "environment_stage": entry.environment.stage.value,
        "environment_label": entry.environment.label,
        "action": entry.action,
        "target": entry.target,
        "outcome": entry.outcome.value,
        "reason": entry.reason.value if entry.reason is not None else None,
        "user_subject": entry.user_subject,
        "username": entry.username,
        "parameters": dict(entry.parameters),
        "correlation_id": entry.correlation_id,
        "client_ip": entry.client_ip,
    }


def _to_entry(row: Row[Any]) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        occurred_at=row.occurred_at,
        environment=EnvironmentIdentity(
            municipality=row.environment_municipality,
            stage=Stage(row.environment_stage),
            label=row.environment_label,
        ),
        action=row.action,
        target=row.target,
        outcome=Outcome(row.outcome),
        reason=ReasonCode(row.reason) if row.reason is not None else None,
        user_subject=row.user_subject,
        username=row.username,
        parameters=row.parameters,
        correlation_id=row.correlation_id,
        # psycopg returns an ipaddress object for inet.
        client_ip=str(row.client_ip) if row.client_ip is not None else None,
    )


class SqlAuditRepository:
    """Stores and reads Audit Entries on the caller's connection.

    Implements both ``AuditRepository`` and ``AuditLogReader``.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def add(self, entry: AuditEntry) -> None:
        """Insert ``entry`` in the caller's transaction. Raises if the database refuses it."""
        await self._connection.execute(insert(audit_entries).values(_to_row(entry)))

    async def search(self, query: AuditLogQuery) -> AuditLogPage:
        """Return the page ``query`` asks for: matching entries, newest first.

        Entries with the same timestamp are ordered by id, so paging never
        shows an entry twice or skips one. The total is counted in the same
        statement as the page, so the two always agree.
        """
        conditions = _conditions(query)
        total_matching = func.count().over().label("total_matching")
        result = await self._connection.execute(
            select(audit_entries, total_matching)
            .where(*conditions)
            .order_by(audit_entries.c.occurred_at.desc(), audit_entries.c.id.desc())
            .limit(AUDIT_LOG_PAGE_SIZE)
            .offset(query.offset)
        )
        rows = result.all()
        if rows:
            total = int(rows[0].total_matching)
        elif query.offset == 0:
            total = 0
        else:
            # A page past the end has no rows to carry the total.
            count = select(func.count()).select_from(audit_entries).where(*conditions)
            total = int((await self._connection.execute(count)).scalar_one())
        return AuditLogPage(
            entries=tuple(_to_entry(row) for row in rows), page=query.page, total=total
        )

    async def get(self, entry_id: uuid.UUID) -> AuditEntry | None:
        """Return the Audit Entry with ``entry_id``, or ``None`` if there is none."""
        result = await self._connection.execute(
            select(audit_entries).where(audit_entries.c.id == entry_id)
        )
        row = result.one_or_none()
        return _to_entry(row) if row is not None else None
