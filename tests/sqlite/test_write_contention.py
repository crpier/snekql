"""SQLite writer-lock contention: IMMEDIATE acquisition and busy retry.

SQLite has one global, exclusive writer lock. A burst of concurrent write
transactions can only ever run one at a time, so the losers must either wait
(``busy_timeout``) or be retried, not surface a hard ``OperationalError`` to the
caller. These cover the two mechanisms that make that true -- ``BEGIN
IMMEDIATE`` for eager, fair writer-lock acquisition and a bounded busy retry
layered on top -- plus the guarantee that a genuinely stuck lock still errors.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory

import anyio
from aiosqlite import Connection, OperationalError
from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Config,
    Fetched,
    Integer,
    Model,
    Pending,
    insert,
)
from snekql.sqlite.pool import close_sqlite_connection, open_sqlite_connection
from snekql.sqlite.retry import BusyRetryPolicy
from snekql.sqlite.runtime import SQLiteConnectionAdapter, initialize_runtime
from tests.helpers import initialized_database


class Counter[S = Pending](Model[S, "Counter[Fetched]"]):
    """Single-column table used to drive concurrent inserts."""

    id: Counter.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )


def _row_count(database_path: Path) -> int:
    connection = connect(database_path)
    try:
        cursor = connection.execute('SELECT count(*) FROM "counter"')
        row = cursor.fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        connection.close()


async def _set_busy_timeout(connection: Connection, milliseconds: int) -> None:
    cursor = await connection.execute(f"PRAGMA busy_timeout = {milliseconds}")
    await cursor.close()


@test(mark="medium")
async def immediate_begin_acquires_the_writer_lock_eagerly() -> None:
    """``BEGIN IMMEDIATE`` takes the writer lock before any statement runs."""

    with TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "app.db")
        holder = await open_sqlite_connection(database_path)
        contender = await open_sqlite_connection(database_path)
        await _set_busy_timeout(contender, 0)
        holder_adapter = SQLiteConnectionAdapter(holder)
        contender_adapter = SQLiteConnectionAdapter(
            contender,
            retry_policy=BusyRetryPolicy(max_retries=0),
        )
        try:
            await holder_adapter.begin("immediate")
            with assert_raises(OperationalError):
                await contender_adapter.begin("immediate")
            await holder_adapter.rollback()
        finally:
            await close_sqlite_connection(holder)
            await close_sqlite_connection(contender)


@test(mark="medium")
async def deferred_begin_leaves_the_writer_lock_free() -> None:
    """A deferred ``BEGIN`` acquires no lock, so a concurrent writer proceeds."""

    with TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "app.db")
        holder = await open_sqlite_connection(database_path)
        contender = await open_sqlite_connection(database_path)
        await _set_busy_timeout(contender, 0)
        holder_adapter = SQLiteConnectionAdapter(holder)
        contender_adapter = SQLiteConnectionAdapter(contender)
        try:
            await holder_adapter.begin("deferred")
            # No lock is held by the deferred holder, so this must not raise.
            await contender_adapter.begin("immediate")
            await contender_adapter.rollback()
            await holder_adapter.rollback()
        finally:
            await close_sqlite_connection(holder)
            await close_sqlite_connection(contender)


@test(mark="medium")
async def busy_begin_retries_into_success_when_the_lock_clears() -> None:
    """A held writer lock that releases within budget is retried into success."""

    with TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "app.db")
        holder = await open_sqlite_connection(database_path)
        contender = await open_sqlite_connection(database_path)
        # Fail fast per attempt so the retry loop, not the PRAGMA wait, drives.
        await _set_busy_timeout(contender, 0)
        holder_adapter = SQLiteConnectionAdapter(holder)
        contender_adapter = SQLiteConnectionAdapter(
            contender,
            retry_policy=BusyRetryPolicy(
                max_retries=200,
                base_backoff=0.001,
                max_backoff=0.005,
            ),
        )
        try:
            await holder_adapter.begin("immediate")

            async def release_holder_soon() -> None:
                await anyio.sleep(0.02)
                await holder_adapter.rollback()

            async with anyio.create_task_group() as task_group:
                task_group.start_soon(release_holder_soon)
                # Retries on busy until the holder releases, then succeeds.
                await contender_adapter.begin("immediate")
            await contender_adapter.rollback()
        finally:
            await close_sqlite_connection(holder)
            await close_sqlite_connection(contender)


@test(mark="medium")
async def a_stuck_writer_lock_still_surfaces_an_error() -> None:
    """A permanently held writer lock surfaces after the retry budget is spent."""

    with TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "app.db")
        holder = await open_sqlite_connection(database_path)
        contender = await open_sqlite_connection(database_path)
        await _set_busy_timeout(contender, 0)
        holder_adapter = SQLiteConnectionAdapter(holder)
        contender_adapter = SQLiteConnectionAdapter(
            contender,
            retry_policy=BusyRetryPolicy(
                max_retries=3,
                base_backoff=0.001,
                max_backoff=0.002,
            ),
        )
        try:
            await holder_adapter.begin("immediate")
            with assert_raises(OperationalError):
                await contender_adapter.begin("immediate")
            await holder_adapter.rollback()
        finally:
            await close_sqlite_connection(holder)
            await close_sqlite_connection(contender)


@test(mark="medium")
async def concurrent_immediate_writers_do_not_surface_lock_errors() -> None:
    """A burst of IMMEDIATE writers serializes cleanly, with no row lost."""

    writer_count = 12
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await initialized_database(
            database=database_path,
            models=[Counter],
            pool_size=5,
        )
        errors: list[BaseException] = []
        try:

            async def write_one() -> None:
                try:
                    async with database.transaction(mode="immediate") as tx:
                        await tx.execute(insert(Counter()))
                except Exception as error:
                    errors.append(error)

            async with anyio.create_task_group() as task_group:
                for _ in range(writer_count):
                    task_group.start_soon(write_one)
        finally:
            await database.close()

        assert_eq(errors, [])
        assert_eq(_row_count(database_path), writer_count)


@test(mark="fast")
async def config_backoff_tuning_reaches_the_runtime_retry_policy() -> None:
    """Backoff knobs on ``Config`` are plumbed into the busy retry policy."""

    config = Config(
        database=":memory:",
        busy_max_retries=9,
        busy_base_backoff=0.05,
        busy_max_backoff=1.5,
    )
    runtime = await initialize_runtime(config)
    try:
        assert_eq(
            runtime.busy_retry_policy,
            BusyRetryPolicy(max_retries=9, base_backoff=0.05, max_backoff=1.5),
        )
    finally:
        await runtime.close(close_timeout=5.0)
