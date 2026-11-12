"""Browsing the Audit Log in PostgreSQL (task 4.3).

Spec: audit-log, "Browsing the Audit Log": newest first, 50 entries per page,
filtered by time range (inclusive), username (case-insensitive substring),
action and outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from podiumd_admin.adapters.db.audit import SqlAuditRepository
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.audit_log import AUDIT_LOG_PAGE_SIZE, AuditLogPage, AuditLogQuery
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from podiumd_admin.ports.audit import AuditLogReader

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
ENVIRONMENT = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.TEST)


def _entry(occurred_at: datetime = NOW, **overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": occurred_at,
        "environment": ENVIRONMENT,
        "action": "sign-in",
        "outcome": Outcome.ALLOWED,
        "correlation_id": "corr",
    }
    fields.update(overrides)
    return AuditEntry(**fields)


def _denied(occurred_at: datetime = NOW, **overrides: Any) -> AuditEntry:
    return _entry(occurred_at, outcome=Outcome.DENIED, reason=ReasonCode.NO_ROLE, **overrides)


async def _store(engine: AsyncEngine, entries: list[AuditEntry]) -> None:
    async with engine.begin() as connection:
        repository = SqlAuditRepository(connection)
        for entry in entries:
            await repository.add(entry)


async def _search(engine: AsyncEngine, **query: Any) -> AuditLogPage:
    async with engine.connect() as connection:
        reader: AuditLogReader = SqlAuditRepository(connection)
        return await reader.search(AuditLogQuery(**query))


def _newest_first(entries: list[AuditEntry]) -> list[AuditEntry]:
    return sorted(entries, key=lambda entry: entry.occurred_at, reverse=True)


async def test_an_empty_audit_log_gives_an_empty_first_page(app_engine: AsyncEngine) -> None:
    page = await _search(app_engine)

    assert page == AuditLogPage(entries=(), page=1, total=0)
    assert page.page_count == 0


async def test_entries_come_newest_first_fifty_per_page(app_engine: AsyncEngine) -> None:
    entries = [_entry(NOW - timedelta(minutes=minute)) for minute in range(120)]
    # Store them out of order, so the order cannot come from insertion.
    await _store(app_engine, entries[::2] + entries[1::2])
    expected = _newest_first(entries)

    first = await _search(app_engine)
    second = await _search(app_engine, page=2)
    third = await _search(app_engine, page=3)

    assert AUDIT_LOG_PAGE_SIZE == 50
    assert list(first.entries) == expected[:50]
    assert list(second.entries) == expected[50:100]
    assert list(third.entries) == expected[100:]
    assert [page.total for page in (first, second, third)] == [120, 120, 120]
    assert [page.page for page in (first, second, third)] == [1, 2, 3]
    assert first.page_count == 3


async def test_a_page_past_the_end_is_empty_but_knows_the_total(app_engine: AsyncEngine) -> None:
    await _store(app_engine, [_entry(NOW - timedelta(minutes=minute)) for minute in range(3)])

    page = await _search(app_engine, page=2)

    assert page == AuditLogPage(entries=(), page=2, total=3)


async def test_entries_with_the_same_timestamp_are_paged_without_overlap(
    app_engine: AsyncEngine,
) -> None:
    entries = [_entry(NOW) for _ in range(AUDIT_LOG_PAGE_SIZE + 10)]
    await _store(app_engine, entries)

    first = await _search(app_engine)
    second = await _search(app_engine, page=2)

    ids_first = {entry.id for entry in first.entries}
    ids_second = {entry.id for entry in second.entries}
    assert len(ids_first) == AUDIT_LOG_PAGE_SIZE
    assert len(ids_second) == 10
    assert ids_first.isdisjoint(ids_second)
    assert ids_first | ids_second == {entry.id for entry in entries}


async def test_the_time_range_includes_both_bounds(app_engine: AsyncEngine) -> None:
    start, end = NOW - timedelta(days=7), NOW
    micro = timedelta(microseconds=1)
    before, at_start, inside, at_end, after = (
        _entry(start - micro),
        _entry(start),
        _entry(start + timedelta(days=3)),
        _entry(end),
        _entry(end + micro),
    )
    await _store(app_engine, [before, at_start, inside, at_end, after])

    page = await _search(app_engine, occurred_from=start, occurred_until=end)

    assert list(page.entries) == [at_end, inside, at_start]
    assert page.total == 3


async def test_the_time_range_may_be_open_on_either_side(app_engine: AsyncEngine) -> None:
    old, new = _entry(NOW - timedelta(days=30)), _entry(NOW)
    await _store(app_engine, [old, new])

    since = await _search(app_engine, occurred_from=NOW - timedelta(days=1))
    until = await _search(app_engine, occurred_until=NOW - timedelta(days=1))

    assert list(since.entries) == [new]
    assert list(until.entries) == [old]


async def test_the_username_filter_matches_any_part_ignoring_case(
    app_engine: AsyncEngine,
) -> None:
    jansen = _entry(NOW, username="j.jansen")
    janssen = _entry(NOW - timedelta(minutes=1), username="P.JANSSEN")
    piet = _entry(NOW - timedelta(minutes=2), username="piet")
    nobody = _entry(NOW - timedelta(minutes=3))
    await _store(app_engine, [jansen, janssen, piet, nobody])

    page = await _search(app_engine, username="Jans")

    assert list(page.entries) == [jansen, janssen]
    assert page.total == 2


@pytest.mark.parametrize(
    ("filter_value", "matches"),
    [
        ("100%", {"100%_zeker"}),
        ("%", {"100%_zeker"}),
        ("%_", {"100%_zeker"}),
        ("_", {"100%_zeker", "a_b"}),
        ("\\", {"back\\slash"}),
    ],
)
async def test_the_username_filter_takes_wildcard_characters_literally(
    app_engine: AsyncEngine, filter_value: str, matches: set[str]
) -> None:
    usernames = ["100%_zeker", "1000-zeker", "a_b", "axb", "back\\slash"]
    await _store(app_engine, [_entry(NOW, username=name) for name in usernames])

    page = await _search(app_engine, username=filter_value)

    assert {entry.username for entry in page.entries} == matches


async def test_the_action_filter_matches_the_whole_action(app_engine: AsyncEngine) -> None:
    sign_in = _entry(NOW, action="sign-in")
    sign_out = _entry(NOW - timedelta(minutes=1), action="sign-out")
    await _store(app_engine, [sign_in, sign_out])

    assert list((await _search(app_engine, action="sign-in")).entries) == [sign_in]
    assert list((await _search(app_engine, action="sign")).entries) == []


@pytest.mark.parametrize("outcome", list(Outcome))
async def test_the_outcome_filter_returns_only_that_outcome(
    app_engine: AsyncEngine, outcome: Outcome
) -> None:
    needs_reason = {Outcome.DENIED: ReasonCode.NO_ROLE, Outcome.INFO: ReasonCode.IDLE}
    entries = [
        _entry(NOW - timedelta(minutes=index), outcome=each, reason=needs_reason.get(each))
        for index, each in enumerate(Outcome)
    ]
    await _store(app_engine, entries)

    page = await _search(app_engine, outcome=outcome)

    assert [entry.outcome for entry in page.entries] == [outcome]
    assert page.total == 1


async def test_denied_attempts_of_the_last_seven_days(app_engine: AsyncEngine) -> None:
    """Spec scenario "Filter on denied attempts", with every filter combined."""
    recent_denied = [
        _denied(NOW - timedelta(days=day), username="j.jansen", action="audit-log:read")
        for day in range(7)
    ]
    others = [
        _denied(NOW - timedelta(days=8), username="j.jansen", action="audit-log:read"),
        _entry(NOW - timedelta(days=1), username="j.jansen", action="audit-log:read"),
        _denied(NOW - timedelta(days=1), username="piet", action="audit-log:read"),
        _denied(NOW - timedelta(days=1), username="j.jansen", action="sign-in"),
    ]
    await _store(app_engine, recent_denied + others)

    page = await _search(
        app_engine,
        occurred_from=NOW - timedelta(days=7),
        occurred_until=NOW,
        username="JANSEN",
        action="audit-log:read",
        outcome=Outcome.DENIED,
    )

    assert list(page.entries) == _newest_first(recent_denied)
    assert page.total == 7


async def test_the_total_counts_all_matches_not_just_the_page(app_engine: AsyncEngine) -> None:
    denied = [_denied(NOW - timedelta(minutes=minute)) for minute in range(60)]
    allowed = [_entry(NOW - timedelta(minutes=minute)) for minute in range(5)]
    await _store(app_engine, denied + allowed)

    page = await _search(app_engine, outcome=Outcome.DENIED)

    assert len(page.entries) == AUDIT_LOG_PAGE_SIZE
    assert page.total == 60
    assert page.page_count == 2
