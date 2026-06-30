"""Bounded retry-with-jitter over SQLite ``SQLITE_BUSY`` writer-lock contention.

SQLite serializes writers behind one global, exclusive writer lock. The
per-connection ``busy_timeout`` PRAGMA already makes a losing writer *wait* for
that lock (rather than failing instantly), but once that wait expires SQLite
raises ``SQLITE_BUSY`` and there is nothing below the application to absorb it.
This module layers a small, bounded retry on top of (and distinct from) the
PRAGMA wait: it re-attempts an operation that failed with ``SQLITE_BUSY``, with
exponential backoff and full jitter to desynchronize colliding writers, and
gives up after a fixed budget so a genuinely stuck lock still surfaces.

Retry is only ever applied to **writer-lock acquisition** (``BEGIN IMMEDIATE``),
never to an individual statement inside an open transaction. Retrying a single
statement is unsafe under WAL: once a transaction has read, a concurrent commit
turns the next write into ``SQLITE_BUSY_SNAPSHOT``, which no amount of
statement-level retry can clear -- the whole transaction must be restarted. The
safe boundary is the lock acquisition that happens before any work, so that is
the only thing this retries.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anyio

from snekql.validation import NonNegativeFloat, NonNegativeInt

logger = logging.getLogger(__name__)

# Default number of retries layered on top of the in-driver ``busy_timeout``
# wait. Each retry re-issues ``BEGIN IMMEDIATE``, which itself waits up to
# ``busy_timeout`` again, so this is a ceiling on collisions absorbed, not a
# duration. Kept small so a stuck lock surfaces in bounded time.
DEFAULT_BUSY_MAX_RETRIES = 5

# Backoff between retries only needs to desynchronize colliding writers; the
# long wait is already provided by ``busy_timeout``. So these are short.
DEFAULT_BUSY_BASE_BACKOFF = 0.01
DEFAULT_BUSY_MAX_BACKOFF = 0.25


@dataclass(frozen=True, kw_only=True)
class BusyRetryPolicy:
    """How many times and how long to retry a busy writer-lock acquisition.

    ``max_retries`` retries follow the first attempt, so the operation runs at
    most ``max_retries + 1`` times. Backoff is exponential in the retry index
    and capped at ``max_backoff``, with full jitter applied per sleep.
    """

    max_retries: NonNegativeInt = DEFAULT_BUSY_MAX_RETRIES
    base_backoff: NonNegativeFloat = DEFAULT_BUSY_BASE_BACKOFF
    max_backoff: NonNegativeFloat = DEFAULT_BUSY_MAX_BACKOFF

    def backoff_for(self, retry_index: int) -> float:
        """Return the jittered backoff (seconds) before the given retry index."""

        ceiling = min(self.max_backoff, self.base_backoff * (2**retry_index))
        return random.uniform(0, ceiling)


DEFAULT_BUSY_RETRY_POLICY = BusyRetryPolicy()


def is_sqlite_busy_error(error: BaseException) -> bool:
    """Return whether ``error`` is a SQLite busy/locked writer-lock contention.

    Matches by the driver error code when present (``SQLITE_BUSY`` and its
    extended variants all share the primary code) and falls back to the message
    so manually constructed and older-driver errors are still recognized.
    """

    if not isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) == sqlite3.SQLITE_BUSY:
        return True
    message = str(error).lower()
    return "database is locked" in message or "database is busy" in message


async def retry_on_sqlite_busy[T](
    operation: Callable[[], Awaitable[T]],
    policy: BusyRetryPolicy = DEFAULT_BUSY_RETRY_POLICY,
) -> T:
    """Run ``operation``, retrying it on ``SQLITE_BUSY`` within ``policy``.

    Returns the operation's value on success. A non-busy exception propagates
    immediately. A busy exception is retried up to ``policy.max_retries`` times
    with jittered backoff; the last busy exception is re-raised once the budget
    is exhausted.
    """

    attempt = 0
    while True:
        try:
            return await operation()
        except sqlite3.OperationalError as error:
            if not is_sqlite_busy_error(error) or attempt >= policy.max_retries:
                raise
            backoff = policy.backoff_for(attempt)
            attempt += 1
            logger.debug(
                "sqlite busy lock contention; retry %d/%d after %.4fs",
                attempt,
                policy.max_retries,
                backoff,
            )
            await anyio.sleep(backoff)


__all__ = [
    "DEFAULT_BUSY_BASE_BACKOFF",
    "DEFAULT_BUSY_MAX_BACKOFF",
    "DEFAULT_BUSY_MAX_RETRIES",
    "DEFAULT_BUSY_RETRY_POLICY",
    "BusyRetryPolicy",
    "is_sqlite_busy_error",
    "retry_on_sqlite_busy",
]
