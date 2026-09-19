"""The opt-in retry example reruns whole transactions without unsafe replay."""

from collections.abc import Iterable
from unittest.mock import patch

from aiosqlite import Connection, Cursor, OperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from examples.transaction_retry import run_with_retry
from snekql import sqlite
from tests.runtime.test_raw_lifecycle import provide_contended_case


@test(mark="medium")
async def snapshot_conflict_repeats_entire_operation() -> None:
    """The second attempt must reread using a fresh transaction and snapshot."""
    case = await load_fixture(provide_contended_case("sqlite"))
    attempts = 0

    async def update(transaction: sqlite.Transaction) -> object:
        nonlocal attempts
        attempts += 1
        before = await transaction.fetch_one(
            sqlite.raw("SELECT value FROM raw_entries")
        )
        if attempts == 1:
            async with case.database.transaction() as concurrent:
                await concurrent.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
        await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=3"))
        return before["value"]

    observed = await run_with_retry(case.database, update)

    assert_eq((attempts, observed), (2, 2))


@test(mark="medium")
async def retry_count_is_bounded() -> None:
    """Repeated serialization conflicts stop after the third whole attempt."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    attempts = 0

    async def fail_write(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql.startswith("UPDATE"):
            error = OperationalError("snapshot conflict")
            error.sqlite_errorcode = 517
            raise error
        return await native_execute(self, sql, parameters)

    async def update(transaction: sqlite.Transaction) -> None:
        nonlocal attempts
        attempts += 1
        await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=value+1"))

    with (
        patch.object(Connection, "execute", fail_write),
        assert_raises(sqlite.ExecutionError),
    ):
        await run_with_retry(case.database, update)
    assert_eq(attempts, 3)


@test(mark="medium")
async def unique_violation_is_not_retried() -> None:
    """An expected application conflict does not become a transient failure."""
    case = await load_fixture(provide_contended_case("sqlite"))
    attempts = 0

    async def duplicate(transaction: sqlite.Transaction) -> None:
        nonlocal attempts
        attempts += 1
        await transaction.execute(sqlite.raw("INSERT INTO raw_entries VALUES (1)"))

    with assert_raises(sqlite.ExecutionError):
        await run_with_retry(case.database, duplicate)
    assert_eq(attempts, 1)


@test(
    [Param("unknown", name="unknown"), Param("committed", name="committed")],
    mark="medium",
)
async def transient_category_does_not_authorize_commit_replay(outcome: str) -> None:
    """A transient-looking error cannot override uncertain or acknowledged COMMIT."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    native_close = Cursor.close
    attempts = 0
    commit_cursor: Cursor | None = None

    async def fail_ack(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        nonlocal commit_cursor
        cursor = await native_execute(self, sql, parameters)
        if sql == "COMMIT":
            commit_cursor = cursor
            if outcome == "unknown":
                await native_close(cursor)
                error = OperationalError("lost acknowledgement")
                error.sqlite_errorcode = 517
                raise error
        return cursor

    async def fail_cleanup(self: Cursor) -> None:
        if self is commit_cursor:
            error = OperationalError("cleanup failed")
            error.sqlite_errorcode = 517
            raise error
        await native_close(self)

    async def update(transaction: sqlite.Transaction) -> None:
        nonlocal attempts
        attempts += 1
        await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=value+1"))

    with (
        patch.object(Connection, "execute", fail_ack),
        patch.object(Cursor, "close", fail_cleanup),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await run_with_retry(case.database, update)
    assert_eq(attempts, 1)
    async with case.database.transaction() as observer:
        rows = await observer.fetch_all(sqlite.raw("SELECT value FROM raw_entries"))
    assert_eq(rows, [{"value": 2}])


@test(mark="medium")
async def swallowed_terminal_error_cannot_report_success() -> None:
    """A callback must not turn a discarded transaction into a successful result."""
    case = await load_fixture(provide_contended_case("sqlite"))

    async def swallow(transaction: sqlite.Transaction) -> str:
        try:
            await transaction.execute(sqlite.raw("INSERT INTO raw_entries VALUES (1)"))
        except sqlite.ExecutionError:
            return "incorrect success"
        return "inserted"

    with assert_raises(sqlite.TransactionStateError):
        await run_with_retry(case.database, swallow)
