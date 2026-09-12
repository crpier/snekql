"""Validation failures preserve transactional effects and cursor ownership."""

import asyncio
from traceback import format_exception
from typing import Annotated, Any

from pydantic import PlainValidator
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import Transaction
from tests.runtime.test_raw_execution import provide_raw_case, provide_raw_table
from tests.runtime.test_raw_failures import ControlledCursor, substitute_cursor


async def _consume_returning(
    transaction: Transaction[Any],
    statement: sqlite.RawStatement[object] | mariadb.RawStatement[object],
    method: str,
) -> None:
    """Exercise buffered consumption or a stream whose context owns completion."""

    if method == "fetch_chunks":
        async with transaction.fetch_chunks(statement, size=1) as stream:
            await anext(stream)
    else:
        await transaction.fetch_all(statement)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="slow",
)
async def caught_returning_validation_can_commit(
    backend: BackendFamily, method: str
) -> None:
    """A caught validation error does not reverse the statement's write."""

    case = await load_fixture(provide_raw_table(backend))
    statement = case.namespace.raw(
        "INSERT INTO raw_entries VALUES (2) RETURNING value", validate=dict[str, str]
    )
    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultValidationError):
            await _consume_returning(transaction, statement, method)
        pending = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM raw_entries ORDER BY value")
        )
    async with case.database.transaction() as transaction:
        committed = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM raw_entries ORDER BY value")
        )

    assert_eq(pending, [{"value": 1}, {"value": 2}])
    assert_eq(committed, pending)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="slow",
)
async def uncaught_returning_validation_rolls_back(
    backend: BackendFamily, method: str
) -> None:
    """Escaping validation failures retain the existing Transaction rollback."""

    case = await load_fixture(provide_raw_table(backend))
    statement = case.namespace.raw(
        "INSERT INTO raw_entries VALUES (2) RETURNING value", validate=dict[str, str]
    )
    with assert_raises(case.namespace.RawResultValidationError):
        async with case.database.transaction() as transaction:
            await _consume_returning(transaction, statement, method)
    async with case.database.transaction() as transaction:
        remaining = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM raw_entries ORDER BY value")
        )

    assert_eq(remaining, [{"value": 1}])


@test(mark="medium")
async def width_failure_precedes_user_validation() -> None:
    """Malformed driver row width is rejected without invoking the contract."""

    cursor = ControlledCursor()
    calls: list[object] = []

    def observe(row: object) -> object:
        calls.append(row)
        return row

    statement = sqlite.raw(
        "SELECT 1", validate=Annotated[object, PlainValidator(observe)]
    )
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with substitute_cursor(cursor), assert_raises(sqlite.RawResultShapeError):
            await transaction.fetch_one(statement)

    assert_eq(calls, [])
    assert_eq(cursor.closed, True)


@test(
    [Param(value=kind, name=kind) for kind in ("validation", "cancel", "interrupt")],
    mark="medium",
)
async def failed_completion_respects_control_flow(kind: str) -> None:
    """Cleanup wins over validation, but never over cancellation or process control."""

    cursor = ControlledCursor(rows=((1,),), failure="cleanup")

    def reject(row: object) -> object:
        del row
        if kind == "cancel":
            raise asyncio.CancelledError
        if kind == "interrupt":
            raise KeyboardInterrupt
        msg = "validator_secret"
        raise sqlite.DatabaseRuntimeError(msg)

    expected = {
        "validation": sqlite.ExecutionError,
        "cancel": asyncio.CancelledError,
        "interrupt": KeyboardInterrupt,
    }[kind]
    statement = sqlite.raw(
        "SELECT 1", validate=Annotated[object, PlainValidator(reject)]
    )
    async with await sqlite.Database.initialize(database=":memory:") as database:
        with assert_raises(expected) as raised:
            async with database.transaction() as transaction:
                with substitute_cursor(cursor):
                    async with transaction.fetch_chunks(statement, size=1) as stream:
                        await anext(stream)
        async with database.transaction() as transaction:
            row = await transaction.fetch_one(sqlite.raw("SELECT 42 AS amount"))

    assert_eq(row, {"amount": 42})
    rendered = "".join(format_exception(raised.exception))
    assert_eq("validator_secret" in rendered, False)
    assert_eq("cleanup_secret" in rendered, False)


@test(
    [Param(value=method, name=method) for method in ("fetch_all", "fetch_chunks")],
    mark="slow",
)
async def additional_results_precede_validation_failure(method: str) -> None:
    """First-row failure cannot hide an extra MariaDB result during completion."""

    case = await load_fixture(provide_raw_case("mariadb"))
    statement = case.namespace.raw(
        "SELECT 'input_secret' AS amount; SELECT 2", validate=dict[str, int]
    )
    with assert_raises(mariadb.RawResultShapeError) as raised:
        async with case.database.transaction() as transaction:
            await _consume_returning(transaction, statement, method)

    rendered = "".join(format_exception(raised.exception))
    assert_eq("input_secret" in rendered, False)
    assert_eq("RawResultValidationError" in rendered, False)


@test(mark="medium")
async def completion_timeout_supersedes_validation() -> None:
    """An uncertain cursor cannot be reused after a validation failure."""

    class SlowCompletion(ControlledCursor):
        async def complete(self) -> bool:
            await asyncio.sleep(1)
            return False

    cursor = SlowCompletion(rows=((1,),))
    statement = sqlite.raw("SELECT 1", validate=dict[str, str])
    async with await sqlite.Database.initialize(database=":memory:") as database:
        with assert_raises(sqlite.DatabaseOperationTimeoutError) as raised:
            async with database.transaction(timeout=0.03) as transaction:
                with substitute_cursor(cursor):
                    async with transaction.fetch_chunks(statement, size=1) as stream:
                        await anext(stream)
        async with database.transaction() as transaction:
            recovered = await transaction.fetch_one(sqlite.raw("SELECT 42 AS amount"))

    assert_eq(raised.exception.operation, "raw cursor completion")
    assert_eq(
        "RawResultValidationError" in "".join(format_exception(raised.exception)), False
    )
    assert_eq(recovered, {"amount": 42})
