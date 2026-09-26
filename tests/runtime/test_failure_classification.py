"""Structured database failures observed through public Transactions."""

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import FrozenInstanceError
from io import StringIO
from sqlite3 import OperationalError
from unittest.mock import patch

from aiomysql import Cursor, Pool
from aiosqlite import Connection as SQLiteConnection
from aiosqlite import Cursor as SQLiteCursor
from anyio import fail_after
from pymysql.err import OperationalError as MariaDBOperationalError
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.runtime.test_nested_recovery import SQLiteEntry, provide_constraint_case
from tests.runtime.test_raw_lifecycle import provide_contended_case


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def duplicate_key_has_portable_category(backend: BackendFamily) -> None:
    """Raw failures retain structured evidence without exposing driver messages."""
    case = await load_fixture(provide_constraint_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.ExecutionError) as caught:
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )

    failure = caught.exception.failure
    assert failure is not None
    assert_eq(failure.category, "unique_violation")
    assert_eq(failure.backend, backend)
    assert_eq(failure.code, 1555 if backend == "sqlite" else 1062)
    assert_eq(failure.sqlstate, None if backend == "sqlite" else "23000")
    assert_eq(failure.constraint, None)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    [
        Param(
            (
                "INSERT INTO constrained_entries VALUES (2, 'existing', 1, 1)",
                "unique_violation",
                2067,
                1062,
            ),
            name="unique",
        ),
        Param(
            (
                "INSERT INTO constrained_entries VALUES (2, NULL, 1, 1)",
                "not_null_violation",
                1299,
                1048,
            ),
            name="not-null",
        ),
        Param(
            (
                "INSERT INTO constrained_entries VALUES (2, 'new', 0, 1)",
                "check_violation",
                275,
                4025,
            ),
            name="check",
        ),
        Param(
            (
                "INSERT INTO constrained_entries VALUES (2, 'new', 1, 99)",
                "foreign_key_violation",
                787,
                1452,
            ),
            name="foreign-key",
        ),
        Param(
            (
                "DELETE FROM nested_entries WHERE value=1",
                "foreign_key_violation",
                787,
                1451,
            ),
            name="referenced-parent",
        ),
    ],
    mark="slow",
)
async def native_constraints_keep_distinct_categories(
    backend: BackendFamily, violation: tuple[str, str, int, int]
) -> None:
    """Classification does not depend on potentially sensitive server messages."""
    case = await load_fixture(provide_constraint_case(backend))
    sql, category, sqlite_code, mariadb_code = violation

    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.ExecutionError) as caught:
            await transaction.execute(case.namespace.raw(sql))

    failure = caught.exception.failure
    assert failure is not None
    assert_eq(failure.category, category)
    assert_eq(failure.code, sqlite_code if backend == "sqlite" else mariadb_code)


@test(mark="medium")
async def sqlite_busy_is_lock_conflict() -> None:
    """An engine busy response differs from the application's operation deadline."""
    case = await load_fixture(provide_contended_case("sqlite"))

    async with case.database.transaction() as holder:
        await holder.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
        async with case.database.transaction() as contender:
            await contender.fetch_all(sqlite.raw("PRAGMA busy_timeout=0"))
            with assert_raises(sqlite.ExecutionError) as caught:
                await contender.execute(sqlite.raw("UPDATE raw_entries SET value=3"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("lock_conflict", 5))


@test(mark="medium")
async def sqlite_stale_snapshot_is_serialization_conflict() -> None:
    """An old WAL snapshot cannot be upgraded to a writer after another commit."""
    case = await load_fixture(provide_contended_case("sqlite"))

    async with case.database.transaction() as reader:
        await reader.fetch_all(sqlite.raw("SELECT value FROM raw_entries"))
        async with case.database.transaction() as writer:
            await writer.execute(sqlite.raw("UPDATE raw_entries SET value=2"))
        with assert_raises(sqlite.ExecutionError) as caught:
            await reader.execute(sqlite.raw("UPDATE raw_entries SET value=3"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("serialization_conflict", 517))


@test(mark="slow")
async def mariadb_nowait_is_lock_conflict() -> None:
    """A native NOWAIT response is classified without treating it as recoverable."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction() as holder:
        await holder.fetch_all(mariadb.raw("SELECT * FROM raw_entries FOR UPDATE"))
        async with case.database.transaction(timeout=1) as contender:
            with assert_raises(mariadb.ExecutionError) as caught:
                await contender.fetch_all(
                    mariadb.raw("SELECT * FROM raw_entries FOR UPDATE NOWAIT")
                )
    failure = caught.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("lock_conflict", 1205))


@test(mark="slow")
async def mariadb_deadlock_is_distinct_from_serialization_sqlstate() -> None:
    """The server's deadlock code refines its broader 40001 SQLSTATE."""
    case = await load_fixture(provide_contended_case("mariadb"))
    async with case.database.transaction() as transaction:
        await transaction.execute(mariadb.raw("INSERT INTO raw_entries VALUES (2)"))
    barrier = asyncio.Barrier(2)

    async def contend(first: int, second: int) -> mariadb.DatabaseFailure | None:
        async with case.database.transaction(timeout=3) as transaction:
            try:
                await transaction.execute(
                    mariadb.raw(
                        "UPDATE raw_entries SET value=value WHERE value=%s",
                        params=(first,),
                    )
                )
                await barrier.wait()
                await transaction.execute(
                    mariadb.raw(
                        "UPDATE raw_entries SET value=value WHERE value=%s",
                        params=(second,),
                    )
                )
            except mariadb.ExecutionError as e:
                return e.failure
        return None

    with fail_after(10):
        outcomes = await asyncio.gather(contend(1, 2), contend(2, 1))
    failures = [failure for failure in outcomes if failure is not None]
    assert_eq(len(failures), 1)
    assert_eq(
        (failures[0].category, failures[0].code, failures[0].sqlstate),
        ("deadlock", 1213, "40001"),
    )


@test(
    [
        Param((2006, None, "connection_loss"), name="gone-away"),
        Param((2013, None, "connection_loss"), name="lost"),
        Param((2055, None, "connection_loss"), name="extended-lost"),
        Param((1927, "70100", "connection_loss"), name="killed"),
        Param((9999, "40001", "serialization_conflict"), name="serialization-state"),
        Param((9999, "08006", "connection_loss"), name="connection-state"),
        Param((9999, "HY000", "unknown"), name="unknown"),
        Param((9999, "08???", "unknown"), name="malformed-state"),
    ],
    mark="slow",
)
async def mariadb_driver_evidence_survives_translation(
    packet: tuple[int, str | None, str],
) -> None:
    """Driver fault injection covers protocol errors without parsing message text."""
    case = await load_fixture(provide_constraint_case("mariadb"))
    code, sqlstate, category = packet

    async def fail_execute(self: Cursor, query: str, args: object = None) -> int:
        del self, query, args
        raise MariaDBOperationalError(code, "private_driver_message", sqlstate=sqlstate)

    async with case.database.transaction() as transaction:
        with (
            patch.object(Cursor, "execute", fail_execute),
            assert_raises(mariadb.ExecutionError) as caught,
        ):
            await transaction.fetch_all(mariadb.raw("SELECT value FROM nested_entries"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(
        (failure.category, failure.code, failure.sqlstate), (category, code, sqlstate)
    )


@test(mark="slow")
async def structured_constraint_name_is_available_without_message_parsing() -> None:
    """Optional structured metadata is preserved but omitted from default rendering."""
    case = await load_fixture(provide_constraint_case("mariadb"))

    class NamedConstraintError(MariaDBOperationalError):
        def __init__(self) -> None:
            super().__init__(1062, "private_driver_message", sqlstate="23000")
            self.constraint_name: str = "private_constraint_name"

    async def fail_execute(self: Cursor, query: str, args: object = None) -> int:
        del self, query, args
        raise NamedConstraintError

    async with case.database.transaction() as transaction:
        with (
            patch.object(Cursor, "execute", fail_execute),
            assert_raises(mariadb.ExecutionError) as caught,
        ):
            await transaction.fetch_all(mariadb.raw("SELECT value FROM nested_entries"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(failure.constraint, "private_constraint_name")
    assert "private_" not in repr(failure) + str(caught.exception)


@test(
    [
        Param("BEGIN", name="begin"),
        Param("COMMIT", name="commit"),
        Param("SAVEPOINT", name="savepoint"),
    ],
    mark="medium",
)
async def transaction_control_keeps_failure_metadata(command: str) -> None:
    """Control errors use the same native evidence without requiring a query error."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = SQLiteConnection.execute

    async def fail_control(
        self: SQLiteConnection, sql: str, parameters: Iterable[object] | None = None
    ) -> SQLiteCursor:
        if sql.startswith(command):
            error = OperationalError("private_driver_value")
            error.sqlite_errorcode = 10
            raise error
        return await native_execute(self, sql, parameters)

    with (
        patch.object(SQLiteConnection, "execute", fail_control),
        assert_raises(sqlite.DatabaseRuntimeError) as caught,
    ):
        async with case.database.transaction() as transaction:
            if command == "SAVEPOINT":
                async with transaction.begin_nested():
                    pass
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(
        (failure.backend, failure.category, failure.code), ("sqlite", "unknown", 10)
    )


@test(
    [
        Param("BEGIN", name="begin"),
        Param("COMMIT", name="commit"),
        Param("ROLLBACK", name="rollback"),
    ],
    mark="medium",
)
async def transaction_control_logs_omit_driver_values(command: str) -> None:
    """Transaction cleanup must not leak values through exc_info or pending errors."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = SQLiteConnection.execute
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")

    async def fail_control(
        self: SQLiteConnection, sql: str, parameters: Iterable[object] | None = None
    ) -> SQLiteCursor:
        if sql.startswith(command):
            message = "private_driver_value"
            raise OperationalError(message)
        return await native_execute(self, sql, parameters)

    logger.addHandler(handler)
    try:
        with (
            patch.object(SQLiteConnection, "execute", fail_control),
            assert_raises(sqlite.DatabaseRuntimeError, sqlite.ModelValidationError),
        ):
            async with case.database.transaction():
                if command == "ROLLBACK":
                    message = "application aborted"
                    raise sqlite.ModelValidationError(message)
    finally:
        logger.removeHandler(handler)
    assert "private_driver_value" not in captured.getvalue()


@test(
    [
        Param("fetchall", name="buffered-fetch"),
        Param("fetchmany", name="stream-fetch"),
        Param("close", name="stream-close"),
    ],
    mark="medium",
)
async def late_cursor_failure_keeps_classification(operation: str) -> None:
    """Late driver failures get metadata but never become savepoint-recoverable."""
    case = await load_fixture(provide_constraint_case("sqlite"))

    async def fail_cursor(
        self: SQLiteCursor, size: int = 1
    ) -> list[tuple[object, ...]]:
        del self, size
        error = OperationalError("private_driver_value")
        error.sqlite_errorcode = 5
        raise error

    async with case.database.transaction() as transaction:
        with (
            patch.object(SQLiteCursor, operation, fail_cursor),
            assert_raises(sqlite.ExecutionError) as caught,
        ):
            if operation == "fetchall":
                await transaction.fetch_all(sqlite.select(SQLiteEntry))
            else:
                async with transaction.fetch_chunks(
                    sqlite.select(SQLiteEntry), size=1
                ) as stream:
                    await anext(stream)
        with assert_raises(sqlite.DatabaseRuntimeError):
            await transaction.fetch_all(sqlite.select(SQLiteEntry))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("lock_conflict", 5))


@test(mark="slow")
async def killed_mariadb_connection_has_portable_category() -> None:
    """Real connection termination must not require applications to inspect driver types."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction() as victim:
        identity = await victim.fetch_one(
            mariadb.raw("SELECT CONNECTION_ID() AS connection_id")
        )
        async with case.database.transaction() as killer:
            await killer.execute(
                mariadb.raw("KILL CONNECTION %s", params=(identity["connection_id"],))
            )
        with assert_raises(mariadb.ExecutionError) as caught:
            await victim.fetch_one(mariadb.raw("SELECT 1"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(failure.category, "connection_loss")


@test(mark="slow")
async def acquisition_driver_failure_uses_runtime_error() -> None:
    """A pool connector failure uses the same portable metadata as query IO."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async def fail_acquire(self: Pool) -> None:
        del self
        message = "private_driver_value"
        raise MariaDBOperationalError(2013, message)

    with (
        patch.object(Pool, "_acquire", fail_acquire),
        assert_raises(mariadb.DatabaseRuntimeError) as caught,
    ):
        async with case.database.transaction():
            pass
    failure = caught.exception.failure
    assert failure is not None
    assert_eq((failure.category, failure.code), ("connection_loss", 2013))


@test(mark="medium")
async def classification_does_not_make_rollback_conflict_recoverable() -> None:
    """A unique category cannot prove that a savepoint or its transaction survived."""
    case = await load_fixture(provide_constraint_case("sqlite"))

    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.ExecutionError) as caught:
            async with transaction.begin_nested():
                await transaction.execute(
                    sqlite.raw("INSERT OR ROLLBACK INTO nested_entries VALUES (1)")
                )
        with assert_raises(sqlite.DatabaseRuntimeError):
            await transaction.fetch_one(sqlite.raw("SELECT 1"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(failure.category, "unique_violation")


@test(mark="fast")
def application_errors_have_no_driver_evidence() -> None:
    """Local misuse and application deadlines do not invent a backend or driver code."""
    assert_eq(sqlite.TransactionClosedError("closed").failure, None)
    assert_eq(sqlite.DatabaseOperationTimeoutError("select", 1).failure, None)


@test(mark="fast")
def failure_metadata_is_immutable() -> None:
    """Captured evidence cannot change while callers decide how to handle it."""
    failure = sqlite.DatabaseFailure(
        backend="sqlite", category="unique_violation", code=1555
    )
    with assert_raises(FrozenInstanceError):
        failure.code = 1  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def missing_native_code_does_not_trigger_message_guessing() -> None:
    """A constraint-looking message is not structured evidence of a unique violation."""
    case = await load_fixture(provide_constraint_case("sqlite"))

    async def fail_fetch(self: SQLiteCursor) -> list[tuple[object, ...]]:
        del self
        message = "UNIQUE constraint failed: private_table.private_value"
        raise OperationalError(message)

    async with case.database.transaction() as transaction:
        with (
            patch.object(SQLiteCursor, "fetchall", fail_fetch),
            assert_raises(sqlite.ExecutionError) as caught,
        ):
            await transaction.fetch_all(sqlite.select(SQLiteEntry))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(
        (failure.category, failure.code, failure.constraint, failure.sqlstate),
        ("unknown", None, None, None),
    )


@test(mark="medium")
async def non_driver_exception_does_not_supply_native_evidence() -> None:
    """An unrelated exception cannot impersonate a driver using attribute names."""
    case = await load_fixture(provide_constraint_case("sqlite"))

    class ImpostorError(sqlite.ModelValidationError):
        def __init__(self) -> None:
            super().__init__("application error")
            self.sqlite_errorcode: int = 1555

    async def fail_fetch(self: SQLiteCursor) -> list[tuple[object, ...]]:
        del self
        raise ImpostorError

    async with case.database.transaction() as transaction:
        with (
            patch.object(SQLiteCursor, "fetchall", fail_fetch),
            assert_raises(sqlite.ExecutionError) as caught,
        ):
            await transaction.fetch_all(sqlite.select(SQLiteEntry))
    assert_eq(caught.exception.failure, None)


@test(mark="slow")
async def late_returning_constraint_retains_native_evidence() -> None:
    """An unbuffered error keeps its category without making uncertain IO recoverable."""
    case = await load_fixture(provide_constraint_case("mariadb"))

    async with case.database.transaction() as transaction:
        with assert_raises(mariadb.ExecutionError) as caught:
            async with (
                transaction.begin_nested(),
                transaction.fetch_chunks(
                    mariadb.raw(
                        "INSERT INTO nested_entries VALUES (2), (1) RETURNING value"
                    ),
                    size=1,
                ) as stream,
            ):
                await anext(stream)
        with assert_raises(mariadb.DatabaseRuntimeError):
            await transaction.fetch_one(mariadb.raw("SELECT 1"))
    failure = caught.exception.failure
    assert failure is not None
    assert_eq(
        (failure.category, failure.code, failure.sqlstate),
        ("unique_violation", 1062, "23000"),
    )
