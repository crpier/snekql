"""Bounded retry-with-jitter over SQLite ``SQLITE_BUSY`` lock contention.

These cover the backend-local retry helper in isolation: it absorbs transient
writer-lock collisions, leaves the value path untouched on success, re-raises a
genuinely stuck lock after a bounded number of attempts, and never swallows an
unrelated error.
"""

from __future__ import annotations

import sqlite3

from snektest import assert_eq, assert_raises, test

from snekql.sqlite.retry import (
    BusyRetryPolicy,
    is_sqlite_busy_error,
    retry_on_sqlite_busy,
)

# Tiny backoff keeps the timing-dependent tests fast while still exercising the
# real ``anyio.sleep`` path between attempts.
_FAST_POLICY = BusyRetryPolicy(max_retries=3, base_backoff=0.0001, max_backoff=0.001)


def _busy_error() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


@test(mark="fast")
def busy_error_is_classified_by_message() -> None:
    """A locked/busy ``OperationalError`` is recognized even without a code."""

    assert_eq(
        is_sqlite_busy_error(sqlite3.OperationalError("database is locked")), True
    )
    assert_eq(is_sqlite_busy_error(sqlite3.OperationalError("database is busy")), True)


@test(mark="fast")
def unrelated_errors_are_not_classified_as_busy() -> None:
    """Non-busy failures must not be mistaken for lock contention."""

    assert_eq(is_sqlite_busy_error(sqlite3.OperationalError("no such table: t")), False)
    assert_eq(is_sqlite_busy_error(ValueError("nope")), False)


@test(mark="fast")
async def successful_operation_runs_once_and_returns_value() -> None:
    """No contention means a single call and the value passes straight through."""

    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await retry_on_sqlite_busy(operation, _FAST_POLICY)

    assert_eq(result, "ok")
    assert_eq(calls, 1)


@test(mark="fast")
async def transient_contention_is_absorbed() -> None:
    """A lock that clears within the retry budget is retried into success."""

    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise _busy_error()
        return "ok"

    result = await retry_on_sqlite_busy(operation, _FAST_POLICY)

    assert_eq(result, "ok")
    assert_eq(calls, 3)


@test(mark="fast")
async def a_stuck_lock_is_reraised_after_bounded_attempts() -> None:
    """A permanently held lock surfaces the busy error after the budget is spent."""

    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise _busy_error()

    with assert_raises(sqlite3.OperationalError):
        _ = await retry_on_sqlite_busy(operation, _FAST_POLICY)

    # One initial attempt plus ``max_retries`` retries.
    assert_eq(calls, 4)


@test(mark="fast")
async def non_busy_errors_propagate_immediately() -> None:
    """An unrelated error is not retried and surfaces on the first attempt."""

    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        message = "no such table: t"
        raise sqlite3.OperationalError(message)

    with assert_raises(sqlite3.OperationalError):
        _ = await retry_on_sqlite_busy(operation, _FAST_POLICY)

    assert_eq(calls, 1)
