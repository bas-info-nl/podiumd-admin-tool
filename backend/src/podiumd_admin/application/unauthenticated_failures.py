"""Combining unauthenticated failures into at most one stdout line per minute.

Spec: audit-log, "Recording unauthenticated failures". Design D4: failures
without an authenticated user (a sign-in callback with a bad ``state`` or an
error, a failed token exchange, a request without a valid session) are written
to stdout only, never to the database. Identical failures, meaning the same
client IP and reason, are combined into at most one line per window (one
minute) that carries a count.

A window starts at the first failure for its key and is written once it is
over: when the next failure is recorded, or by ``flush``, which the app calls
periodically so a final burst is not held back. ``flush_all`` writes every
open window, for example at shutdown.

Memory is bounded: at most ``max_clients`` distinct client IPs are tracked
separately, each with at most one window per reason. Failures from further
client IPs are combined per reason into one overflow line without a client
IP, so a flood from many addresses cannot grow the table.

Every window has the same length and is opened at the current time, so the
windows, kept in the order they were opened, are also in the order they end.
Flushing therefore only looks at the oldest windows and stops at the first
one that is still open; the cost does not grow with the number of open
windows. If the clock steps back, a window may be written up to that step
late, never early. The sink is called after the lock is released, so slow stdout I/O
does not hold up other callers.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from podiumd_admin.domain.audit import (
    UNAUTHENTICATED_REASONS,
    ReasonCode,
    UnauthenticatedFailureSummary,
    normalise_client_ip,
)
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock

DEFAULT_WINDOW: Final = timedelta(minutes=1)
DEFAULT_MAX_CLIENTS: Final = 10_000

type _Key = tuple[str | None, ReasonCode]


@dataclass(slots=True)
class _Window:
    first_at: datetime
    last_at: datetime
    count: int = 1


class UnauthenticatedFailureAggregator:
    """Counts unauthenticated failures per (client IP, reason) and writes one line per window.

    Thread-safe, so it can be shared by async handlers and by sync
    dependencies that run in a thread pool.
    """

    def __init__(
        self,
        *,
        sink: AuditSink,
        clock: Clock,
        window: timedelta = DEFAULT_WINDOW,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> None:
        if window <= timedelta(0):
            raise ValueError(f"window must be positive, got {window}")
        if max_clients < 1:
            raise ValueError(f"max_clients must be at least 1, got {max_clients}")
        self._sink = sink
        self._clock = clock
        self._window = window
        self._max_clients = max_clients
        # Ordered by first_at, so the oldest windows end first.
        self._windows: OrderedDict[_Key, _Window] = OrderedDict()
        # Open windows per tracked client IP; its length is the number of
        # distinct client IPs tracked.
        self._windows_per_client: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def window(self) -> timedelta:
        """How long failures are combined before their line is written."""
        return self._window

    def record(self, client_ip: str, reason: ReasonCode) -> None:
        """Count one unauthenticated failure from ``client_ip`` for ``reason``.

        Raises ``ValueError`` if ``reason`` is not an unauthenticated-failure
        reason or ``client_ip`` is not an IP address.
        """
        if reason not in UNAUTHENTICATED_REASONS:
            raise ValueError(f"reason {reason!r} is not an unauthenticated-failure reason")
        address = normalise_client_ip(client_ip)

        with self._lock:
            now = self._clock.now()
            ended = self._take_ended(now)
            key = self._key_for(address, reason)
            window = self._windows.get(key)
            if window is None:
                self._windows[key] = _Window(first_at=now, last_at=now)
                if key[0] is not None:
                    self._windows_per_client[key[0]] = self._windows_per_client.get(key[0], 0) + 1
            else:
                window.count += 1
                window.last_at = now
        self._write(ended)

    def flush(self) -> None:
        """Write a line for every window that is over."""
        with self._lock:
            ended = self._take_ended(self._clock.now())
        self._write(ended)

    def flush_all(self) -> None:
        """Write a line for every window, including those still open."""
        with self._lock:
            ended = [self._take(key) for key in list(self._windows)]
        self._write(ended)

    def _key_for(self, address: str, reason: ReasonCode) -> _Key:
        if address in self._windows_per_client or len(self._windows_per_client) < self._max_clients:
            return (address, reason)
        return (None, reason)

    def _take_ended(self, now: datetime) -> list[UnauthenticatedFailureSummary]:
        """Remove the windows that are over, oldest first. Call with the lock held."""
        ended: list[UnauthenticatedFailureSummary] = []
        while self._windows:
            key, window = next(iter(self._windows.items()))
            if now - window.first_at < self._window:
                break
            ended.append(self._take(key))
        return ended

    def _take(self, key: _Key) -> UnauthenticatedFailureSummary:
        """Remove one window and return its line. Call with the lock held."""
        window = self._windows.pop(key)
        client_ip, reason = key
        if client_ip is not None:
            remaining = self._windows_per_client[client_ip] - 1
            if remaining:
                self._windows_per_client[client_ip] = remaining
            else:
                del self._windows_per_client[client_ip]
        return UnauthenticatedFailureSummary(
            client_ip=client_ip,
            reason=reason,
            count=window.count,
            first_at=window.first_at,
            last_at=window.last_at,
        )

    def _write(self, summaries: list[UnauthenticatedFailureSummary]) -> None:
        """Hand lines to the sink. Call without the lock held."""
        for summary in summaries:
            self._sink.unauthenticated_failures(summary)
