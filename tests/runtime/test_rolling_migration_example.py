"""Bounded, durable backfill batches before a coordinated contract migration."""

import asyncio
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aiomysql import Connection as MariaDBConnection
from aiomysql.cursors import Cursor as MariaDBCursor
from aiosqlite import Connection as SQLiteConnection
from aiosqlite import Cursor as SQLiteCursor
from aiosqlite import OperationalError as SQLiteOperationalError
from anyio import CancelScope, Event, TemporaryDirectory, fail_after, sleep_forever
from pymysql.err import OperationalError as MariaDBOperationalError
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from examples.rolling_migration import (
    MARIADB_CONTRACTED,
    MARIADB_EXPANDED,
    SQLITE_CONTRACTED,
    SQLITE_EXPANDED,
    BackfillError,
    backfill_mariadb_batch,
    backfill_sqlite_batch,
    contract_mariadb,
    contract_sqlite,
)
from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import Database
from tests.helpers import provide_mariadb_server
from tests.runtime.test_raw_execution import RawCase, provide_raw_case


@dataclass(frozen=True)
class ExpandedCase(RawCase):
    config: sqlite.Config | mariadb.Config


@fixture
async def provide_expanded(backend: BackendFamily) -> AsyncGenerator[ExpandedCase]:
    async with TemporaryDirectory() as directory:
        if backend == "sqlite":
            config = sqlite.Config(database=Path(directory) / "rollout.db", pool_size=2)
            namespace = sqlite
        else:
            server = await load_fixture(provide_mariadb_server())
            config = server.config(pool_size=2)
            namespace = mariadb
        async with await Database.initialize(config) as database:
            case = ExpandedCase(database, namespace, config)
            migrations = SQLITE_EXPANDED if backend == "sqlite" else MARIADB_EXPANDED
            await database.migrate({"001_customers": migrations["001_customers"]})
            async with database.transaction() as transaction:
                await transaction.execute(
                    namespace.raw(
                        "INSERT INTO rollout_customer VALUES (1, 'Ada'), (3, 'Grace'), (9, 'Linus')"
                    )
                )
            await database.migrate(migrations)
            yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def batch_advances_a_bounded_checkpoint(backend: BackendFamily) -> None:
    """A batch handles at most its page size and persists the last observed primary key."""
    case = await load_fixture(provide_expanded(backend))

    progress = await (
        backfill_sqlite_batch(case.database, batch_size=2)
        if backend == "sqlite"
        else backfill_mariadb_batch(case.database, batch_size=2)
    )
    async with case.database.transaction() as transaction:
        checkpoint = await transaction.fetch_one(
            case.namespace.raw("SELECT last_id FROM rollout_backfill WHERE id=1")
        )

    assert_eq(progress.last_id, 3)
    assert_eq(progress.updated, 2)
    assert_eq(progress.done, False)
    assert_eq(checkpoint, {"last_id": 3})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def backfill_resumes_from_durable_checkpoint(backend: BackendFamily) -> None:
    """A restarted worker reads its progress from the database, not process memory."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    await backfill(case.database, batch_size=2)
    await case.database.close()

    async with await Database.initialize(case.config) as restarted:
        progress = await backfill(restarted, batch_size=2)
        async with restarted.transaction() as transaction:
            rows = await transaction.fetch_all(
                case.namespace.raw(
                    "SELECT display_name FROM rollout_customer ORDER BY id"
                )
            )

    assert_eq(progress.last_id, 9)
    assert_eq(progress.updated, 1)
    assert_eq(progress.done, True)
    assert_eq(
        rows,
        [{"display_name": "Ada"}, {"display_name": "Grace"}, {"display_name": "Linus"}],
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def concurrent_workers_serialize_checkpoint_progress(
    backend: BackendFamily,
) -> None:
    """Two workers cannot both advance from an unlocked checkpoint."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch

    progress = await asyncio.gather(
        backfill(case.database, batch_size=1), backfill(case.database, batch_size=1)
    )

    assert_eq(sorted(batch.last_id for batch in progress), [1, 3])
    assert_eq(sum(batch.updated for batch in progress), 2)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def backfill_does_not_overwrite_populated_target(backend: BackendFamily) -> None:
    """A non-null target belongs to the application and must not be clobbered."""
    case = await load_fixture(provide_expanded(backend))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw(
                "UPDATE rollout_customer SET display_name='Reviewed' WHERE id=1"
            )
        )
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch

    progress = await backfill(case.database, batch_size=1)
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(
            case.namespace.raw("SELECT display_name FROM rollout_customer WHERE id=1")
        )

    assert_eq(progress.updated, 0)
    assert_eq(progress.last_id, 1)
    assert_eq(row, {"display_name": "Reviewed"})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=0, name="zero"),
        Param(value=-1, name="negative"),
        Param(value=1001, name="too-large"),
        Param(value=True, name="boolean"),
    ],
    mark="slow",
)
async def invalid_batch_size_is_rejected_before_io(
    backend: BackendFamily, size: int
) -> None:
    """A bounded batch never accepts boolean or invalid page sizes."""
    case = await load_fixture(provide_expanded(backend))
    await case.database.close()
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch

    with assert_raises(BackfillError):
        await backfill(case.database, batch_size=size)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def contract_refuses_incomplete_backfill(backend: BackendFamily) -> None:
    """Contract must prove current row contents, not trust a worker's progress report."""
    case = await load_fixture(provide_expanded(backend))

    with assert_raises(BackfillError):
        await (
            contract_sqlite(case.database)
            if backend == "sqlite"
            else contract_mariadb(case.database)
        )
    await case.database.verify_migrations(
        SQLITE_EXPANDED if backend == "sqlite" else MARIADB_EXPANDED
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value="failure", name="failure"), Param(value="cancel", name="cancel")],
    mark="slow",
)
async def interrupted_checkpoint_rolls_back_copied_rows(
    backend: BackendFamily, mode: str
) -> None:
    """Updates and progress cannot become durable independently, even on cancellation."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    reached_checkpoint = Event()
    native_sqlite = SQLiteConnection.execute
    native_mariadb = MariaDBCursor.execute

    async def interrupt() -> None:
        reached_checkpoint.set()
        if mode == "cancel":
            await sleep_forever()
        msg = "injected checkpoint failure"
        if backend == "sqlite":
            raise SQLiteOperationalError(msg)
        raise MariaDBOperationalError(2013, msg)

    async def sqlite_execute(
        self: SQLiteConnection, sql: str, parameters: Iterable[object] = ()
    ) -> SQLiteCursor:
        if sql.startswith("UPDATE rollout_backfill SET"):
            await interrupt()
        return await native_sqlite(self, sql, parameters)

    async def mariadb_execute(self: MariaDBCursor, sql: str, args: Any = None) -> Any:
        if sql.startswith("UPDATE rollout_backfill SET"):
            await interrupt()
        return await native_mariadb(self, sql, args)

    with (
        patch.object(SQLiteConnection, "execute", sqlite_execute),
        patch.object(MariaDBCursor, "execute", mariadb_execute),
        fail_after(3),
    ):
        task = asyncio.create_task(backfill(case.database, batch_size=2))
        try:
            await reached_checkpoint.wait()
            if mode == "cancel":
                task.cancel()
                with assert_raises(asyncio.CancelledError):
                    await task
            else:
                with assert_raises(case.namespace.ExecutionError):
                    await task
        finally:
            task.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)

    async with case.database.transaction() as transaction:
        checkpoint = await transaction.fetch_one(
            case.namespace.raw("SELECT last_id FROM rollout_backfill WHERE id=1")
        )
        copied = await transaction.fetch_one(
            case.namespace.raw(
                "SELECT COUNT(*) AS count FROM rollout_customer WHERE display_name IS NOT NULL"
            )
        )
    assert_eq(checkpoint, {"last_id": 0})
    assert_eq(copied, {"count": 0})
    progress = await backfill(case.database, batch_size=2)
    assert_eq(progress.last_id, 3)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="out-of-date", name="mismatched"),
        Param(value="Ada ", name="trailing-space"),
    ],
    mark="slow",
)
async def contract_rejects_disagreeing_values(
    backend: BackendFamily, value: str
) -> None:
    """The final rename check compares actual values, including MariaDB trailing spaces."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    await backfill(case.database)
    async with case.database.transaction() as transaction:
        marker = ":value" if backend == "sqlite" else "%(value)s"
        await transaction.execute(
            case.namespace.raw(
                f"UPDATE rollout_customer SET display_name={marker} WHERE id=1",
                params={"value": value},
            )
        )

    with assert_raises(BackfillError):
        await (
            contract_sqlite(case.database)
            if backend == "sqlite"
            else contract_mariadb(case.database)
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def contract_preserves_backfilled_values(backend: BackendFamily) -> None:
    """The coordinated contract removes old storage without losing copied names."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    await backfill(case.database)

    await (
        contract_sqlite(case.database)
        if backend == "sqlite"
        else contract_mariadb(case.database)
    )
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT * FROM rollout_customer ORDER BY id")
        )

    assert_eq(
        rows,
        [
            {"id": 1, "display_name": "Ada"},
            {"id": 3, "display_name": "Grace"},
            {"id": 9, "display_name": "Linus"},
        ],
    )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def fresh_replay_reaches_the_contracted_schema(backend: BackendFamily) -> None:
    """An empty database replays the same literal chain, without a separate bootstrap path."""
    case = await load_fixture(provide_raw_case(backend))
    declaration = SQLITE_CONTRACTED if backend == "sqlite" else MARIADB_CONTRACTED

    await case.database.migrate(declaration)
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw(
                "INSERT INTO rollout_customer (id, display_name) VALUES (1, 'New')"
            )
        )
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT * FROM rollout_customer")
        )
    await case.database.verify_migrations(declaration)

    assert_eq(rows, [{"id": 1, "display_name": "New"}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def lost_commit_reply_resumes_from_committed_progress(
    backend: BackendFamily,
) -> None:
    """Checkpoint inspection reconciles an uncertain commit without repeating external work."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    sqlite_execute = SQLiteConnection.execute
    mariadb_commit = MariaDBConnection.commit

    async def sqlite_lost_reply(
        self: SQLiteConnection, sql: str, parameters: Iterable[object] = ()
    ) -> SQLiteCursor:
        cursor = await sqlite_execute(self, sql, parameters)
        if sql == "COMMIT":
            await cursor.close()
            msg = "injected lost commit reply"
            raise SQLiteOperationalError(msg)
        return cursor

    async def mariadb_lost_reply(self: MariaDBConnection) -> None:
        await mariadb_commit(self)
        msg = "injected lost commit reply"
        raise MariaDBOperationalError(2013, msg)

    with (
        patch.object(SQLiteConnection, "execute", sqlite_lost_reply),
        patch.object(MariaDBConnection, "commit", mariadb_lost_reply),
        assert_raises(case.namespace.DatabaseRuntimeError),
    ):
        await backfill(case.database, batch_size=2)
    await case.database.close()

    async with await Database.initialize(case.config) as restarted:
        progress = await backfill(restarted, batch_size=2)

    assert_eq(progress.last_id, 9)
    assert_eq(progress.updated, 1)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def dual_writer_racing_backfill_keeps_current_values(
    backend: BackendFamily,
) -> None:
    """Either lock order preserves the bridge writer's atomic change to both columns."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch

    async def bridge_write() -> None:
        async with case.database.transaction() as transaction:
            await transaction.execute(
                case.namespace.raw(
                    "UPDATE rollout_customer SET name='Current', display_name='Current' WHERE id=1"
                )
            )

    await asyncio.gather(backfill(case.database), bridge_write())
    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(
            case.namespace.raw(
                "SELECT name, display_name FROM rollout_customer WHERE id=1"
            )
        )

    assert_eq(row, {"name": "Current", "display_name": "Current"})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def completed_checkpoint_does_not_authorize_contract(
    backend: BackendFamily,
) -> None:
    """An old-only writer can insert behind the cursor; final data checks must catch it."""
    case = await load_fixture(provide_expanded(backend))
    backfill = backfill_sqlite_batch if backend == "sqlite" else backfill_mariadb_batch
    await backfill(case.database)
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw(
                "INSERT INTO rollout_customer (id, name) VALUES (2, 'Late')"
            )
        )

    progress = await backfill(case.database)

    assert_eq(progress.done, True)
    with assert_raises(BackfillError):
        await (
            contract_sqlite(case.database)
            if backend == "sqlite"
            else contract_mariadb(case.database)
        )
