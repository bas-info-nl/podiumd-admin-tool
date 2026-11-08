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

Memory is bounded: at most ``max_clients`` keys are tracked separately.
Failures for further keys are combined per reason into one overflow line
without a client IP, so a flood from many addresses cannot grow the table.
"""

from __future__ import annotations

import threading
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
        self._windows: dict[_Key, _Window] = {}
        self._tracked_clients = 0
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
            self._flush_ended(now)
            key = self._key_for(address, reason)
            window = self._windows.get(key)
            if window is None:
                self._windows[key] = _Window(first_at=now, last_at=now)
                if key[0] is not None:
                    self._tracked_clients += 1
            else:
                window.count += 1
                window.last_at = now

    def flush(self) -> None:
        """Write a line for every window that is over."""
        with self._lock:
            self._flush_ended(self._clock.now())

    def flush_all(self) -> None:
        """Write a line for every window, including those still open."""
        with self._lock:
            for key in list(self._windows):
                self._emit(key)

    def _key_for(self, address: str, reason: ReasonCode) -> _Key:
        key: _Key = (address, reason)
        if key in self._windows or self._tracked_clients < self._max_clients:
            return key
        return (None, reason)

    def _flush_ended(self, now: datetime) -> None:
        ended = [
            key for key, window in self._windows.items() if now - window.first_at >= self._window
        ]
        for key in ended:
            self._emit(key)

    def _emit(self, key: _Key) -> None:
        window = self._windows.pop(key)
        client_ip, reason = key
        if client_ip is not None:
            self._tracked_clients -= 1
        self._sink.unauthenticated_failures(
            UnauthenticatedFailureSummary(
                client_ip=client_ip,
                reason=reason,
                count=window.count,
                first_at=window.first_at,
                last_at=window.last_at,
            )
        )
