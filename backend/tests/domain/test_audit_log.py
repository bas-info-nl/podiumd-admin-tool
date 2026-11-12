"""Browsing the Audit Log: the query a reader sends and the page they get back.

Spec: audit-log, "Browsing the Audit Log": newest first, 50 entries per page,
filtered by time range (inclusive), username (case-insensitive substring),
action and outcome. The query validates its values, so the persistence
adapter only ever sees a well-formed one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from podiumd_admin.domain.audit import (
    MAX_ACTION_LENGTH,
    MAX_USERNAME_LENGTH,
    AuditEntry,
    Outcome,
)
from podiumd_admin.domain.audit_log import (
    AUDIT_LOG_PAGE_SIZE,
    MAX_PAGE,
    AuditLogPage,
    AuditLogQuery,
    InvalidAuditLogQueryError,
)
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage

START = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)


def _query(**fields: Any) -> AuditLogQuery:
    """Build a query from untyped fields, to test values the type checker would reject."""
    return AuditLogQuery(**fields)


def test_the_page_size_is_fifty() -> None:
    assert AUDIT_LOG_PAGE_SIZE == 50


def test_an_empty_query_matches_everything_on_the_first_page() -> None:
    query = AuditLogQuery()

    assert query.occurred_from is None
    assert query.occurred_until is None
    assert query.username is None
    assert query.action is None
    assert query.outcome is None
    assert query.page == 1
    assert query.offset == 0


@pytest.mark.parametrize(("page", "offset"), [(1, 0), (2, 50), (3, 100)])
def test_the_offset_follows_from_the_page(page: int, offset: int) -> None:
    assert AuditLogQuery(page=page).offset == offset


@pytest.mark.parametrize("page", [0, -1, MAX_PAGE + 1])
def test_a_page_outside_the_allowed_range_is_rejected(page: int) -> None:
    with pytest.raises(InvalidAuditLogQueryError, match="page"):
        AuditLogQuery(page=page)


@pytest.mark.parametrize("page", [True, 1.0, "1"])
def test_a_page_must_be_a_whole_number(page: Any) -> None:
    with pytest.raises(InvalidAuditLogQueryError, match="page"):
        AuditLogQuery(page=page)


def test_the_highest_page_is_accepted() -> None:
    assert AuditLogQuery(page=MAX_PAGE).page == MAX_PAGE


def test_the_time_range_is_converted_to_utc() -> None:
    amsterdam = timezone(timedelta(hours=1))

    query = AuditLogQuery(
        occurred_from=datetime(2026, 11, 1, 1, 0, tzinfo=amsterdam),
        occurred_until=datetime(2026, 11, 8, 1, 0, tzinfo=amsterdam),
    )

    assert query.occurred_from == START
    assert query.occurred_from.tzinfo is UTC
    assert query.occurred_until == END


@pytest.mark.parametrize("field", ["occurred_from", "occurred_until"])
def test_a_naive_bound_is_rejected(field: str) -> None:
    naive = datetime(2026, 11, 1, 0, 0)  # noqa: DTZ001 - the invalid value under test

    with pytest.raises(InvalidAuditLogQueryError, match=field):
        _query(**{field: naive})


@pytest.mark.parametrize("field", ["occurred_from", "occurred_until"])
def test_a_bound_must_be_a_datetime(field: str) -> None:
    with pytest.raises(InvalidAuditLogQueryError, match=field):
        _query(**{field: "2026-11-01"})


def test_a_range_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(InvalidAuditLogQueryError, match="before"):
        AuditLogQuery(occurred_from=END, occurred_until=START)


def test_a_range_of_one_instant_is_accepted() -> None:
    query = AuditLogQuery(occurred_from=START, occurred_until=START)

    assert query.occurred_from == query.occurred_until == START


def test_either_bound_may_be_left_open() -> None:
    assert AuditLogQuery(occurred_from=START).occurred_until is None
    assert AuditLogQuery(occurred_until=END).occurred_from is None


@pytest.mark.parametrize("field", ["username", "action"])
def test_text_filters_are_trimmed(field: str) -> None:
    query = _query(**{field: "  jan  "})

    assert getattr(query, field) == "jan"


@pytest.mark.parametrize("field", ["username", "action"])
@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_text_filter_means_no_filter(field: str, value: str) -> None:
    assert getattr(_query(**{field: value}), field) is None


@pytest.mark.parametrize(
    ("field", "limit"), [("username", MAX_USERNAME_LENGTH), ("action", MAX_ACTION_LENGTH)]
)
def test_a_text_filter_longer_than_the_stored_field_is_rejected(field: str, limit: int) -> None:
    assert getattr(_query(**{field: "a" * limit}), field) == "a" * limit

    with pytest.raises(InvalidAuditLogQueryError, match=field):
        _query(**{field: "a" * (limit + 1)})


@pytest.mark.parametrize("field", ["username", "action"])
def test_a_text_filter_must_be_text(field: str) -> None:
    with pytest.raises(InvalidAuditLogQueryError, match=field):
        _query(**{field: 42})


def test_the_outcome_filter_takes_an_outcome() -> None:
    assert AuditLogQuery(outcome=Outcome.DENIED).outcome is Outcome.DENIED


def test_the_outcome_filter_rejects_free_text() -> None:
    with pytest.raises(InvalidAuditLogQueryError, match="outcome"):
        AuditLogQuery(outcome="denied")  # type: ignore[arg-type]


# --- AuditLogPage ---------------------------------------------------------------


def _entry() -> AuditEntry:
    return AuditEntry(
        occurred_at=START,
        environment=EnvironmentIdentity(municipality="Onsdorp", stage=Stage.TEST),
        action="sign-in",
        outcome=Outcome.ALLOWED,
        correlation_id="c-1",
    )


@pytest.mark.parametrize(
    ("total", "page_count"), [(0, 0), (1, 1), (50, 1), (51, 2), (100, 2), (101, 3)]
)
def test_the_page_count_follows_from_the_total(total: int, page_count: int) -> None:
    page = AuditLogPage(entries=(), page=1, total=total)

    assert page.page_count == page_count
    assert page.page_size == AUDIT_LOG_PAGE_SIZE


def test_a_page_holds_its_entries_in_order() -> None:
    first, second = _entry(), _entry()

    page = AuditLogPage(entries=(first, second), page=1, total=2)

    assert page.entries == (first, second)


def test_a_page_never_holds_more_than_the_page_size() -> None:
    with pytest.raises(ValueError, match="at most"):
        AuditLogPage(entries=(_entry(),) * (AUDIT_LOG_PAGE_SIZE + 1), page=1, total=51)


def test_a_page_never_holds_more_entries_than_the_total() -> None:
    with pytest.raises(ValueError, match="total"):
        AuditLogPage(entries=(_entry(), _entry()), page=1, total=1)


@pytest.mark.parametrize(("page", "total"), [(0, 0), (1, -1)])
def test_a_page_rejects_impossible_numbers(page: int, total: int) -> None:
    with pytest.raises(ValueError, match=r"page|total"):
        AuditLogPage(entries=(), page=page, total=total)
