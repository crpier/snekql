"""Builder execution regressions using real connections on both backends."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from anyio import fail_after, to_thread
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import DatabaseOperationTimeoutError, MultipleResultsError
from snekql.model import BackendFamily
from snekql.query import _ExecutableOptionalSelect, _ExecutableWrite
from snekql.runtime import Database
from tests.helpers import initialized_database, provide_mariadb_server


class _SQLiteEntry[S = sqlite.Pending](sqlite.Model[S, "_SQLiteEntry[sqlite.Fetched]"]):
    """SQLite rows used to observe transaction-local writes."""

    id: _SQLiteEntry.Col[int] = sqlite.Integer(primary_key=True)
    label: _SQLiteEntry.Col[str] = sqlite.Text()


class _MariaDBEntry[S = mariadb.Pending](
    mariadb.Model[S, "_MariaDBEntry[mariadb.Fetched]"]
):
    """MariaDB rows used to observe transaction-local writes."""

    id: _MariaDBEntry.Col[int] = mariadb.Integer(primary_key=True)
    label: _MariaDBEntry.Col[str] = mariadb.Text()


type FetchMethod = Literal[
    "fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks"
]


type EntryQuery = _ExecutableOptionalSelect[Any, Any, Any, tuple[int, str]]


@dataclass(frozen=True)
class _ExecutionCase:
    """Equivalent builder operations pinned to the fixture's actual backend."""

    database: Database[Any]
    many: EntryQuery
    one: EntryQuery
    update: _ExecutableWrite[Any, int]


@fixture
async def _provide_execution_case(
    backend: BackendFamily,
) -> AsyncGenerator[_ExecutionCase]:
    """Seed independent rows and leave a second connection available for contention."""

    if backend == "mariadb":
        server = await load_fixture(provide_mariadb_server())
        async with await initialized_database(
            server.config(pool_size=2), models=[_MariaDBEntry]
        ) as database:
            async with database.transaction() as transaction:
                await transaction.execute(
                    mariadb.insert(
                        [_MariaDBEntry(id=index, label="seed") for index in range(1, 4)]
                    )
                )
            yield _ExecutionCase(
                database=database,
                many=mariadb.select(_MariaDBEntry.id, _MariaDBEntry.label)
                .all()
                .order_by(_MariaDBEntry.id.asc()),
                one=mariadb.select(_MariaDBEntry.id, _MariaDBEntry.label).where(
                    _MariaDBEntry.id.eq(1)
                ),
                update=mariadb.update(_MariaDBEntry)
                .set(_MariaDBEntry.label.to("pending"))
                .where(_MariaDBEntry.id.eq(1)),
            )
        return
    directory = await to_thread.run_sync(TemporaryDirectory[str])
    try:
        async with await initialized_database(
            database=Path(directory.name) / "execution.db",
            pool_size=2,
            models=[_SQLiteEntry],
        ) as database:
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.insert(
                        [_SQLiteEntry(id=index, label="seed") for index in range(1, 4)]
                    )
                )
            yield _ExecutionCase(
                database=database,
                many=sqlite.select(_SQLiteEntry.id, _SQLiteEntry.label)
                .all()
                .order_by(_SQLiteEntry.id.asc()),
                one=sqlite.select(_SQLiteEntry.id, _SQLiteEntry.label).where(
                    _SQLiteEntry.id.eq(1)
                ),
                update=sqlite.update(_SQLiteEntry)
                .set(_SQLiteEntry.label.to("pending"))
                .where(_SQLiteEntry.id.eq(1)),
            )
    finally:
        await to_thread.run_sync(directory.cleanup)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param[FetchMethod](value="fetch_all", name="fetch_all"),
        Param[FetchMethod](value="fetch_one", name="fetch_one"),
        Param[FetchMethod](value="fetch_one_or_none", name="fetch_one_or_none"),
        Param[FetchMethod](value="fetch_chunks", name="fetch_chunks"),
    ],
    mark="slow",
)
async def reads_see_transaction_local_writes(
    backend: BackendFamily,
    method: FetchMethod,
) -> None:
    """Each consumption method reads on the connection that owns the pending write."""

    case = await load_fixture(_provide_execution_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(case.update)
        match method:
            case "fetch_all":
                observed = await transaction.fetch_all(case.one)
            case "fetch_one":
                observed = [await transaction.fetch_one(case.one)]
            case "fetch_one_or_none":
                observed = [await transaction.fetch_one_or_none(case.one)]
            case "fetch_chunks":
                async with transaction.fetch_chunks(case.one, size=1) as stream:
                    observed = [row async for chunk in stream for row in chunk]

    assert_eq(observed, [(1, "pending")])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def caught_cardinality_failure_leaves_connection_usable(
    backend: BackendFamily,
) -> None:
    """Capped reads close unread rows before reporting excess cardinality."""

    case = await load_fixture(_provide_execution_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(MultipleResultsError):
            await transaction.fetch_one(case.many)
        observed = await transaction.fetch_one(case.one)

    assert_eq(observed, (1, "seed"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def early_stream_exit_releases_connection_lock(backend: BackendFamily) -> None:
    """Unread streamed rows cannot obstruct the next operation on the transaction."""

    case = await load_fixture(_provide_execution_case(backend))

    with fail_after(5):
        async with case.database.transaction() as transaction:
            async with transaction.fetch_chunks(case.many, size=1) as stream:
                await anext(stream)
            observed = await transaction.fetch_one(case.one)

    assert_eq(observed, (1, "seed"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def blocked_write_obeys_operation_deadline(backend: BackendFamily) -> None:
    """A real lock wait times out and the disposed slot admits subsequent work."""

    case = await load_fixture(_provide_execution_case(backend))

    async with case.database.transaction() as owner:
        await owner.execute(case.update)
        with assert_raises(DatabaseOperationTimeoutError):
            async with case.database.transaction(timeout=0.05) as waiter:
                await waiter.execute(case.update)
    with fail_after(5):
        async with case.database.transaction() as transaction:
            observed = await transaction.fetch_one(case.one)

    assert_eq(observed, (1, "pending"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def cancelled_write_releases_pool_capacity(backend: BackendFamily) -> None:
    """Native cancellation during a real lock wait cannot leak the second slot."""

    case = await load_fixture(_provide_execution_case(backend))
    started = asyncio.Event()

    async def wait_for_write() -> None:
        async with case.database.transaction() as waiter:
            started.set()
            await waiter.execute(case.update)

    async with case.database.transaction() as owner:
        await owner.execute(case.update)
        pending = asyncio.create_task(wait_for_write())
        try:
            await started.wait()
            await asyncio.sleep(0.02)
            pending.cancel()
            with assert_raises(asyncio.CancelledError):
                await pending
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    with fail_after(5):
        async with case.database.transaction() as transaction:
            observed = await transaction.fetch_one(case.one)

    assert_eq(observed, (1, "pending"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def stream_holds_transaction_lock_until_context_exit(
    backend: BackendFamily,
) -> None:
    """A competing task cannot execute on a connection with an open stream."""

    case = await load_fixture(_provide_execution_case(backend))

    with fail_after(5):
        async with case.database.transaction() as transaction:
            async with transaction.fetch_chunks(case.many, size=1) as stream:
                pending = asyncio.create_task(transaction.fetch_one(case.one))
                try:
                    await asyncio.sleep(0.02)
                    assert_eq(pending.done(), False)
                    await anext(stream)
                except BaseException:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    raise
            observed = await pending

    assert_eq(observed, (1, "seed"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def uncaught_cardinality_error_rolls_back_pending_write(
    backend: BackendFamily,
) -> None:
    """Application-side cardinality failure retains ordinary rollback semantics."""

    case = await load_fixture(_provide_execution_case(backend))

    with assert_raises(MultipleResultsError):
        async with case.database.transaction() as transaction:
            await transaction.execute(case.update)
            await transaction.fetch_one_or_none(case.many)
    async with case.database.transaction() as transaction:
        observed = await transaction.fetch_one(case.one)

    assert_eq(observed, (1, "seed"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def write_returns_connector_affected_rowcount(backend: BackendFamily) -> None:
    """Buffered execution captures the first response's rowcount before close."""

    case = await load_fixture(_provide_execution_case(backend))

    async with case.database.transaction() as transaction:
        affected = await transaction.execute(case.update)

    assert_eq(affected, 1)
