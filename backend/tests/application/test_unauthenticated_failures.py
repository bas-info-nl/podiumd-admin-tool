"""Combining unauthenticated failures into at most one stdout line per minute.

Spec: audit-log, "Recording unauthenticated failures". Design D4: failures
without an authenticated user go to stdout only. A per-(client IP, reason)
aggregator emits at most one line per minute with a count, so anonymous
traffic cannot flood the Audit Log. The tests drive time with a fake Clock.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from podiumd_admin.application.unauthenticated_failures import (
    UnauthenticatedFailureAggregator,
)
from podiumd_admin.domain.audit import (
    UNAUTHENTICATED_REASONS,
    ReasonCode,
    UnauthenticatedFailureSummary,
)
from podiumd_admin.ports.clock import Clock
from tests.application.fakes import FakeAuditSink, FakeClock

START = datetime(2026, 11, 8, 9, 30, 15, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
IP = "192.0.2.10"
OTHER_IP = "198.51.100.7"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def sink() -> FakeAuditSink:
    return FakeAuditSink()


@pytest.fixture
def aggregator(sink: FakeAuditSink, clock: FakeClock) -> UnauthenticatedFailureAggregator:
    return UnauthenticatedFailureAggregator(sink=sink, clock=clock)


def test_fake_clock_satisfies_the_port(clock: FakeClock) -> None:
    typed_clock: Clock = clock

    assert typed_clock.now() == START


def test_burst_of_invalid_callbacks_gives_one_line_with_the_count(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    # Spec scenario "Burst of invalid callbacks": 500 within one minute.
    for _ in range(500):
        aggregator.record(IP, ReasonCode.INVALID_STATE)
        clock.advance(timedelta(milliseconds=100))

    assert sink.summaries == []

    clock.current = START + MINUTE
    aggregator.flush()

    assert sink.summaries == [
        UnauthenticatedFailureSummary(
            client_ip=IP,
            reason=ReasonCode.INVALID_STATE,
            count=500,
            first_at=START,
            last_at=START + timedelta(milliseconds=100 * 499),
        )
    ]


def test_nothing_is_written_before_the_minute_is_over(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record(IP, ReasonCode.NO_SESSION)
    clock.advance(MINUTE - timedelta(microseconds=1))

    aggregator.flush()

    assert sink.summaries == []


def test_a_single_failure_is_written_with_count_one(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record(IP, ReasonCode.NO_SESSION)
    clock.advance(MINUTE)

    aggregator.flush()

    assert [summary.count for summary in sink.summaries] == [1]


def test_a_window_is_written_only_once(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record(IP, ReasonCode.NO_SESSION)
    clock.advance(MINUTE)

    aggregator.flush()
    aggregator.flush()
    clock.advance(MINUTE)
    aggregator.flush()

    assert len(sink.summaries) == 1


def test_steady_failures_give_at_most_one_line_per_minute_per_key(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    # One failure per second for ten minutes, with a flush every second.
    for _ in range(600):
        aggregator.record(IP, ReasonCode.INVALID_STATE)
        aggregator.flush()
        clock.advance(timedelta(seconds=1))
    aggregator.flush_all()

    starts = [summary.first_at for summary in sink.summaries]
    assert all(later - earlier >= MINUTE for earlier, later in itertools.pairwise(starts))
    assert sum(summary.count for summary in sink.summaries) == 600
    assert len(sink.summaries) == 10


def test_a_failure_after_the_minute_writes_the_previous_line_and_starts_a_new_one(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record(IP, ReasonCode.INVALID_STATE)
    aggregator.record(IP, ReasonCode.INVALID_STATE)
    clock.advance(MINUTE + timedelta(seconds=5))

    # No explicit flush: recording flushes the windows that are over.
    aggregator.record(IP, ReasonCode.INVALID_STATE)

    assert [(summary.count, summary.first_at) for summary in sink.summaries] == [(2, START)]

    clock.advance(MINUTE)
    aggregator.flush()

    assert [(summary.count, summary.first_at) for summary in sink.summaries] == [
        (2, START),
        (1, START + MINUTE + timedelta(seconds=5)),
    ]


def test_client_ips_and_reasons_are_counted_separately(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record(IP, ReasonCode.INVALID_STATE)
    aggregator.record(IP, ReasonCode.INVALID_STATE)
    aggregator.record(IP, ReasonCode.NO_SESSION)
    aggregator.record(OTHER_IP, ReasonCode.INVALID_STATE)
    clock.advance(MINUTE)

    aggregator.flush()

    assert sorted((s.client_ip, s.reason.value, s.count) for s in sink.summaries) == [
        (IP, "invalid-state", 2),
        (IP, "no-session", 1),
        (OTHER_IP, "invalid-state", 1),
    ]


def test_client_ips_are_normalised_into_one_key(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator.record("2001:DB8:0:0:0:0:0:1", ReasonCode.NO_SESSION)
    aggregator.record(" 2001:db8::1", ReasonCode.NO_SESSION)
    clock.advance(MINUTE)

    aggregator.flush()

    assert [(s.client_ip, s.count) for s in sink.summaries] == [("2001:db8::1", 2)]


def test_flush_all_writes_unfinished_windows(
    aggregator: UnauthenticatedFailureAggregator, sink: FakeAuditSink, clock: FakeClock
) -> None:
    # Used at shutdown, so no counted failure is lost.
    aggregator.record(IP, ReasonCode.CALLBACK_ERROR)
    clock.advance(timedelta(seconds=10))
    aggregator.record(IP, ReasonCode.CALLBACK_ERROR)

    aggregator.flush_all()
    aggregator.flush_all()

    assert [(s.count, s.last_at) for s in sink.summaries] == [(2, START + timedelta(seconds=10))]


@pytest.mark.parametrize("reason", sorted(set(ReasonCode) - UNAUTHENTICATED_REASONS), ids=str)
def test_only_unauthenticated_reasons_are_accepted(
    aggregator: UnauthenticatedFailureAggregator, reason: ReasonCode
) -> None:
    with pytest.raises(ValueError, match="unauthenticated"):
        aggregator.record(IP, reason)


@pytest.mark.parametrize("client_ip", ["testclient", "", "192.0.2.10, 10.0.0.1"])
def test_client_ip_must_be_an_ip_address(
    aggregator: UnauthenticatedFailureAggregator, client_ip: str
) -> None:
    with pytest.raises(ValueError, match="client_ip"):
        aggregator.record(client_ip, ReasonCode.NO_SESSION)


def test_clients_beyond_the_tracking_limit_share_one_overflow_line(
    sink: FakeAuditSink, clock: FakeClock
) -> None:
    # Bounded memory: a flood from many addresses cannot grow the table
    # without limit. Clients that do not fit are combined without an IP.
    aggregator = UnauthenticatedFailureAggregator(sink=sink, clock=clock, max_clients=2)

    for host in range(1, 6):
        aggregator.record(f"192.0.2.{host}", ReasonCode.NO_SESSION)
    aggregator.record("192.0.2.1", ReasonCode.NO_SESSION)
    clock.advance(MINUTE)
    aggregator.flush()

    assert sorted(((s.client_ip or ""), s.count) for s in sink.summaries) == [
        ("", 3),
        ("192.0.2.1", 2),
        ("192.0.2.2", 1),
    ]


def test_tracking_room_is_freed_once_lines_are_written(
    sink: FakeAuditSink, clock: FakeClock
) -> None:
    aggregator = UnauthenticatedFailureAggregator(sink=sink, clock=clock, max_clients=1)
    aggregator.record(IP, ReasonCode.NO_SESSION)
    clock.advance(MINUTE)

    aggregator.record(OTHER_IP, ReasonCode.NO_SESSION)
    clock.advance(MINUTE)
    aggregator.flush()

    assert [s.client_ip for s in sink.summaries] == [IP, OTHER_IP]


@pytest.mark.parametrize("window", [timedelta(0), timedelta(seconds=-1)])
def test_window_must_be_positive(sink: FakeAuditSink, clock: FakeClock, window: timedelta) -> None:
    with pytest.raises(ValueError, match="window"):
        UnauthenticatedFailureAggregator(sink=sink, clock=clock, window=window)


def test_tracking_limit_must_be_positive(sink: FakeAuditSink, clock: FakeClock) -> None:
    with pytest.raises(ValueError, match="max_clients"):
        UnauthenticatedFailureAggregator(sink=sink, clock=clock, max_clients=0)


def test_default_window_is_one_minute(
    aggregator: UnauthenticatedFailureAggregator,
) -> None:
    assert aggregator.window == MINUTE
