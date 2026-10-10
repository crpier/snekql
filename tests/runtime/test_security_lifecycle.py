"""Defensive lifecycle checks through public native runtime boundaries."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

from anyio import Event, fail_after, sleep_forever, to_thread
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.runtime.test_nested_transactions import provide_nested_case


@fixture
async def single_connection_file(
    *, seed: bool = False, observer: sqlite.Observer | None = None
) -> AsyncGenerator[sqlite.Database]:
    """Keep persistent state independent of discarded connection replacement."""
    directory = await to_thread.run_sync(TemporaryDirectory[str])
    try:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=Path(directory.name) / "review.db", pool_size=1),
            observer=observer,
        ) as database:
            await database.migrate(
                {"001": "CREATE TABLE entries (value INTEGER PRIMARY KEY) STRICT"}
            )
            if seed:
                async with database.transaction() as transaction:
                    await transaction.execute(
                        sqlite.raw("INSERT INTO entries VALUES (1)")
                    )
            yield database
    finally:
        await to_thread.run_sync(directory.cleanup)


@test([Param(delay, name=f"checkpoint-{delay}") for delay in range(8)], mark="medium")
async def repeated_cancellation_recovers_pool_capacity(delay: int) -> None:
    """A second native cancellation during rollback cannot strand a lease."""
    database = await load_fixture(single_connection_file())
    ready = Event()

    async def writer() -> None:
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.raw("INSERT INTO entries VALUES (1)"))
            ready.set()
            await sleep_forever()

    pending = asyncio.create_task(writer())
    await ready.wait()
    pending.cancel()
    for _ in range(delay):
        await asyncio.sleep(0)
    pending.cancel()
    with assert_raises(asyncio.CancelledError):
        await pending

    with fail_after(5):
        async with database.transaction(timeout=1) as transaction:
            rows = await transaction.fetch_all(sqlite.raw("SELECT value FROM entries"))
    assert_eq(rows, [])


@test(mark="medium")
async def builder_stream_rejects_foreign_task_reads() -> None:
    """A rejected consumer must leave the owning task's cursor untouched."""
    database = await load_fixture(single_connection_file(seed=True))

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        __tablename__ = "entries"
        value: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    async with (
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.select(Entry.value), size=1) as stream,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError):
            await asyncio.create_task(anext(stream))
        rows = await anext(stream)

    assert_eq(rows, [1])


@test(mark="medium")
async def builder_stream_rejects_foreign_task_close() -> None:
    """A foreign exit must not close the cursor or release another task's lock."""
    database = await load_fixture(single_connection_file(seed=True))

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        __tablename__ = "entries"
        value: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    async with (
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.select(Entry.value), size=1) as stream,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError):
            await asyncio.create_task(stream.__aexit__(None, None, None))
        rows = await anext(stream)

    assert_eq(rows, [1])


@test([Param(delay, name=f"checkpoint-{delay}") for delay in range(8)], mark="medium")
async def cancelled_entry_recovers_pool_capacity(delay: int) -> None:
    """Repeated native cancellation during BEGIN cleanup cannot lose a lease."""
    pending: asyncio.Task[None] | None = None
    beginning = Event()

    def observer(event: sqlite.TelemetryEvent) -> None:
        if pending is not None and event.kind == "driver" and event.phase == "start":
            beginning.set()

    database = await load_fixture(single_connection_file(observer=observer))

    async def enter() -> None:
        async with database.transaction():
            await sleep_forever()

    pending = asyncio.create_task(enter())
    await beginning.wait()
    pending.cancel()
    for _ in range(delay):
        await asyncio.sleep(0)
    pending.cancel()
    with assert_raises(asyncio.CancelledError):
        await pending

    async with database.transaction(timeout=1) as transaction:
        rows = await transaction.fetch_one(sqlite.raw("SELECT 1 AS value"))
    assert_eq(rows, {"value": 1})


@test(mark="medium")
async def transaction_exit_requires_owned_stream_to_close() -> None:
    """An owning task cannot wait for a stream lock that only it can release."""
    database = await load_fixture(single_connection_file(seed=True))

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        __tablename__ = "entries"
        value: sqlite.Col[int] = sqlite.Integer(primary_key=True)

    async with (
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.select(Entry.value), size=1) as stream,
    ):
        with assert_raises(sqlite.TransactionStateError):
            await transaction.__aexit__(None, None, None)
        rows = await anext(stream)

    assert_eq(rows, [1])


@test([Param(delay, name=f"checkpoint-{delay}") for delay in range(8)], mark="slow")
async def native_repeated_cancellation_recovers_pool_capacity(delay: int) -> None:
    """MariaDB also retains rollback ownership across repeated native cancellation."""
    case = await load_fixture(provide_nested_case("mariadb"))
    ready = Event()

    async def writer() -> None:
        async with case.database.transaction() as transaction:
            await transaction.execute(
                mariadb.raw("INSERT INTO nested_entries VALUES (1)")
            )
            ready.set()
            await sleep_forever()

    pending = asyncio.create_task(writer())
    await ready.wait()
    pending.cancel()
    for _ in range(delay):
        await asyncio.sleep(0)
    pending.cancel()
    with assert_raises(asyncio.CancelledError):
        await pending

    async with case.database.transaction(timeout=1) as transaction:
        rows = await transaction.fetch_all(
            mariadb.raw("SELECT value FROM nested_entries")
        )
    assert_eq(rows, [])


@test(mark="medium")
async def cleanup_process_control_stays_in_caller() -> None:
    """An observer's SystemExit is delivered only after native cleanup finishes."""
    process_control = SystemExit(17)

    def observer(event: sqlite.TelemetryEvent) -> None:
        if event.kind == "transaction" and event.phase == "finish":
            raise process_control

    database = await load_fixture(single_connection_file(observer=observer))
    transaction = database.transaction()

    with assert_raises(SystemExit) as caught:
        async with transaction:
            pass

    assert_eq(caught.exception, process_control)
    assert_eq(transaction.commit_outcome, "committed")
    assert_eq(database.pool_stats().occupied, 0)
