"""Managed COMMIT evidence survives transaction cleanup and connection disposal."""

import asyncio
from collections.abc import Iterable
from contextlib import suppress
from unittest.mock import patch

from aiomysql import Connection as MariaDBConnection
from aiosqlite import Connection, Cursor, OperationalError
from anyio import Event, fail_after, sleep_forever
from pymysql.err import OperationalError as MariaDBOperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.runtime.test_nested_transactions import provide_nested_case
from tests.runtime.test_raw_lifecycle import provide_contended_case


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def successful_outer_exit_records_commit(backend: BackendFamily) -> None:
    """Only the managed outer COMMIT changes the public outcome."""
    case = await load_fixture(provide_nested_case(backend))
    transaction = case.database.transaction()

    assert_eq(transaction.commit_outcome, "not_attempted")
    async with transaction:
        async with transaction.begin_nested():
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )
        assert_eq(transaction.commit_outcome, "not_attempted")
    assert_eq(transaction.commit_outcome, "committed")


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def application_rollback_never_attempts_commit(backend: BackendFamily) -> None:
    """A rollback is not a rejected COMMIT."""
    case = await load_fixture(provide_nested_case(backend))
    transaction = case.database.transaction()

    with assert_raises(sqlite.ModelValidationError):
        async with transaction:
            message = "abandon work"
            raise sqlite.ModelValidationError(message)
    assert_eq(transaction.commit_outcome, "not_attempted")


@test(mark="medium")
async def deferred_foreign_key_rejects_commit() -> None:
    """SQLite's constraint rejection while still in the transaction proves no commit."""
    case = await load_fixture(provide_nested_case("sqlite"))
    await case.database.migrate(
        {
            "001_entries": "CREATE TABLE nested_entries (value INTEGER PRIMARY KEY)",
            "002_children": "CREATE TABLE children (parent INTEGER REFERENCES nested_entries(value) DEFERRABLE INITIALLY DEFERRED)",
        }
    )
    transaction = case.database.transaction()

    with assert_raises(sqlite.DatabaseRuntimeError) as caught:
        async with transaction:
            await transaction.execute(sqlite.raw("INSERT INTO children VALUES (99)"))
    assert_eq(transaction.commit_outcome, "rejected")
    assert caught.exception.failure is not None
    assert_eq(caught.exception.failure.category, "foreign_key_violation")


@test(mark="medium")
async def restoration_failure_does_not_erase_commit_acknowledgement() -> None:
    """A cleanup exception after COMMIT must not invite duplicate writes on retry."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    transaction = case.database.transaction(read_only=False)

    async def fail_restore(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql.startswith("PRAGMA"):
            message = "restoration failed"
            raise OperationalError(message)
        return await native_execute(self, sql, parameters)

    await transaction.__aenter__()
    await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
    with (
        patch.object(Connection, "execute", fail_restore),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await transaction.__aexit__(None, None, None)
    assert_eq(transaction.commit_outcome, "committed")
    async with case.database.transaction() as observer:
        rows = await observer.fetch_all(sqlite.raw("SELECT value FROM raw_entries"))
    assert_eq(rows, [{"value": 2}])


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def lost_acknowledgement_leaves_committed_write_unknown(
    backend: BackendFamily,
) -> None:
    """Failure at the driver return cannot tell the caller whether COMMIT took effect."""
    case = await load_fixture(provide_contended_case(backend))
    sqlite_execute = Connection.execute
    mariadb_commit = MariaDBConnection.commit
    transaction = case.database.transaction()

    async def lose_sqlite_ack(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        cursor = await sqlite_execute(self, sql, parameters)
        if sql == "COMMIT":
            await cursor.close()
            message = "commit acknowledgement lost"
            raise OperationalError(message)
        return cursor

    async def lose_mariadb_ack(self: MariaDBConnection) -> None:
        await mariadb_commit(self)
        message = "commit acknowledgement lost"
        raise MariaDBOperationalError(2013, message)

    await transaction.__aenter__()
    await transaction.execute(case.namespace.raw("UPDATE raw_entries SET value=2"))
    with (
        patch.object(Connection, "execute", lose_sqlite_ack),
        patch.object(MariaDBConnection, "commit", lose_mariadb_ack),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await transaction.__aexit__(None, None, None)
    assert_eq(transaction.commit_outcome, "unknown")
    async with case.database.transaction() as observer:
        rows = await observer.fetch_all(
            case.namespace.raw("SELECT value FROM raw_entries")
        )
    assert_eq(rows, [{"value": 2}])


@test(
    [
        Param((1213, "rejected"), name="deadlock"),
        Param((9999, "unknown"), name="unproven-rejection"),
    ],
    mark="slow",
)
async def mariadb_commit_rejection_requires_specific_evidence(
    packet: tuple[int, str],
) -> None:
    """A deadlock packet proves rejection; a generic serialization SQLSTATE does not."""
    case = await load_fixture(provide_contended_case("mariadb"))
    code, expected = packet
    transaction = case.database.transaction()

    async def reject_commit(self: MariaDBConnection) -> None:
        del self
        message = "commit failed"
        raise MariaDBOperationalError(code, message, sqlstate="40001")

    with (
        patch.object(MariaDBConnection, "commit", reject_commit),
        assert_raises(mariadb.DatabaseRuntimeError),
    ):
        async with transaction:
            await transaction.execute(mariadb.raw("UPDATE raw_entries SET value=2"))
    assert_eq(transaction.commit_outcome, expected)


@test(
    [
        Param("commit", name="commit"),
        Param("restore", name="restore"),
        Param("cursor_close", name="cursor-close"),
    ],
    [Param("timeout", name="timeout"), Param("cancel", name="cancel")],
    mark="medium",
)
async def interrupted_sqlite_close_preserves_observed_acknowledgement(
    phase: str, interruption: str
) -> None:
    """Only driver acknowledgement, not whether cleanup returned, proves a commit."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    started = Event()
    transaction = case.database.transaction(read_only=False, timeout=0.1)

    async def block_execute(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if (phase == "commit" and sql == "COMMIT") or (
            phase == "restore" and sql.startswith("PRAGMA")
        ):
            started.set()
            await sleep_forever()
        return await native_execute(self, sql, parameters)

    async def block_close(self: Cursor) -> None:
        del self
        started.set()
        await sleep_forever()

    await transaction.__aenter__()
    await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
    driver_patch = (
        patch.object(Cursor, "close", block_close)
        if phase == "cursor_close"
        else patch.object(Connection, "execute", block_execute)
    )
    with driver_patch, fail_after(5):
        closing = asyncio.create_task(transaction.__aexit__(None, None, None))
        try:
            await started.wait()
            if interruption == "cancel":
                closing.cancel()
                with assert_raises(asyncio.CancelledError):
                    await closing
            else:
                with assert_raises(sqlite.DatabaseOperationTimeoutError):
                    await closing
        finally:
            if not closing.done():
                closing.cancel()
                with suppress(asyncio.CancelledError):
                    await closing
    assert_eq(
        transaction.commit_outcome, "unknown" if phase == "commit" else "committed"
    )


@test([Param("timeout", name="timeout"), Param("cancel", name="cancel")], mark="slow")
async def interrupted_mariadb_commit_is_unknown(interruption: str) -> None:
    """Interruption before driver acknowledgement must not promise rollback."""
    case = await load_fixture(provide_contended_case("mariadb"))
    started = Event()
    transaction = case.database.transaction(timeout=0.1)

    async def block_commit(self: MariaDBConnection) -> None:
        del self
        started.set()
        await sleep_forever()

    await transaction.__aenter__()
    with patch.object(MariaDBConnection, "commit", block_commit), fail_after(5):
        closing = asyncio.create_task(transaction.__aexit__(None, None, None))
        try:
            await started.wait()
            if interruption == "cancel":
                closing.cancel()
                with assert_raises(asyncio.CancelledError):
                    await closing
            else:
                with assert_raises(mariadb.DatabaseOperationTimeoutError):
                    await closing
        finally:
            if not closing.done():
                closing.cancel()
                with suppress(asyncio.CancelledError):
                    await closing
    assert_eq(transaction.commit_outcome, "unknown")


@test(mark="medium")
async def constraint_code_without_active_transaction_does_not_prove_rejection() -> None:
    """A late error must not be mistaken for SQLite's deferred-constraint rejection."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    transaction = case.database.transaction()

    async def lose_ack(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        cursor = await native_execute(self, sql, parameters)
        if sql == "COMMIT":
            await cursor.close()
            error = OperationalError("late failure")
            error.sqlite_errorcode = 787
            raise error
        return cursor

    with (
        patch.object(Connection, "execute", lose_ack),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        async with transaction:
            await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
    assert_eq(transaction.commit_outcome, "unknown")


@test(mark="medium")
async def successful_later_lease_does_not_rewrite_previous_outcome() -> None:
    """Each Transaction owns a snapshot, even when it reuses the physical connection."""
    case = await load_fixture(provide_nested_case("sqlite"))
    abandoned = case.database.transaction()
    committed = case.database.transaction()

    with assert_raises(sqlite.ModelValidationError):
        async with abandoned:
            message = "abandon"
            raise sqlite.ModelValidationError(message)
    async with committed:
        pass
    assert_eq(
        (abandoned.commit_outcome, committed.commit_outcome),
        ("not_attempted", "committed"),
    )


@test(mark="medium")
async def commit_outcome_is_read_only() -> None:
    """Applications cannot rewrite commit evidence through its public property."""
    case = await load_fixture(provide_nested_case("sqlite"))
    transaction = case.database.transaction()

    with assert_raises(AttributeError):
        transaction.commit_outcome = "committed"  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def sqlite_busy_commit_is_rejected_while_transaction_remains_open() -> None:
    """An engine BUSY response to COMMIT proves rejection, unlike a driver timeout."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute
    transaction = case.database.transaction()

    async def busy_commit(
        self: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql == "COMMIT":
            error = OperationalError("database is locked")
            error.sqlite_errorcode = 5
            raise error
        return await native_execute(self, sql, parameters)

    with (
        patch.object(Connection, "execute", busy_commit),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        async with transaction:
            await transaction.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
    assert_eq(transaction.commit_outcome, "rejected")
