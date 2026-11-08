"""Browsing the Audit Log: the query a reader sends and the page they get back.

Spec: audit-log, "Browsing the Audit Log":

- newest first, ``AUDIT_LOG_PAGE_SIZE`` (50) entries per page;
- filtered by time range (both bounds inclusive), username (case-insensitive
  substring), action (exact) and outcome.

``AuditLogQuery`` validates its values when it is built, so the persistence
adapter only ever receives a well-formed query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from podiumd_admin.domain.audit import (
    MAX_ACTION_LENGTH,
    MAX_USERNAME_LENGTH,
    AuditEntry,
    Outcome,
)

AUDIT_LOG_PAGE_SIZE: Final = 50
MAX_PAGE: Final = 1_000_000_000
"""The highest page number accepted, so the offset always fits a database integer."""


class InvalidAuditLogQueryError(ValueError):
    """An Audit Log query was built with an invalid value."""


def _bound(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidAuditLogQueryError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _text_filter(name: str, value: object, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidAuditLogQueryError(f"{name} must be text when given")
    text = value.strip()
    if len(text) > limit:
        # A longer value can never match a stored field, which is capped at the limit.
        raise InvalidAuditLogQueryError(f"{name} must be at most {limit} characters")
    return text or None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditLogQuery:
    """Which Audit Entries to show, and which page of them.

    Every filter is optional; ``None`` means no filter. ``occurred_from`` and
    ``occurred_until`` are both inclusive and are converted to UTC.
    ``username`` matches any part of the username, ignoring case; ``action``
    matches exactly. Blank text filters count as no filter. ``page`` starts
    at 1.
    """

    occurred_from: datetime | None = None
    occurred_until: datetime | None = None
    username: str | None = None
    action: str | None = None
    outcome: Outcome | None = None
    page: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.page, bool) or not isinstance(self.page, int):
            raise InvalidAuditLogQueryError("page must be a whole number")
        if not 1 <= self.page <= MAX_PAGE:
            raise InvalidAuditLogQueryError(f"page must be between 1 and {MAX_PAGE}")
        if self.outcome is not None and not isinstance(self.outcome, Outcome):
            raise InvalidAuditLogQueryError(f"outcome must be an Outcome, got {self.outcome!r}")

        occurred_from = _bound("occurred_from", self.occurred_from)
        occurred_until = _bound("occurred_until", self.occurred_until)
        if (
            occurred_from is not None
            and occurred_until is not None
            and occurred_until < occurred_from
        ):
            raise InvalidAuditLogQueryError("occurred_until must not be before occurred_from")

        # Normalise in place; object.__setattr__ is the documented way to do
        # this in a frozen dataclass.
        normalised: dict[str, object] = {
            "occurred_from": occurred_from,
            "occurred_until": occurred_until,
            "username": _text_filter("username", self.username, MAX_USERNAME_LENGTH),
            "action": _text_filter("action", self.action, MAX_ACTION_LENGTH),
        }
        for name, value in normalised.items():
            object.__setattr__(self, name, value)

    @property
    def offset(self) -> int:
        """How many matching entries come before this page."""
        return (self.page - 1) * AUDIT_LOG_PAGE_SIZE


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditLogPage:
    """One page of matching Audit Entries, newest first, and how many match in total."""

    entries: tuple[AuditEntry, ...]
    page: int
    total: int
    page_size: int = AUDIT_LOG_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"page must be at least 1, got {self.page}")
        if self.total < 0:
            raise ValueError(f"total must not be negative, got {self.total}")
        if len(self.entries) > self.page_size:
            raise ValueError(f"a page holds at most {self.page_size} entries")
        if len(self.entries) > self.total:
            raise ValueError("a page cannot hold more entries than the total")

    @property
    def page_count(self) -> int:
        """How many pages the matching entries fill; 0 when nothing matches."""
        return -(-self.total // self.page_size)
