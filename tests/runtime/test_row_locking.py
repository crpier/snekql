"""Row locking through real MariaDB Transactions and typed query builders."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import nullcontext, suppress

from anyio import (
    CancelScope,
    Event,
    create_task_group,
    fail_after,
    move_on_after,
    sleep,
)
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_row_locking import Job, JobSummary
from tests.runtime.test_nested_recovery import SQLiteEntry
from tests.runtime.test_nested_transactions import provide_nested_case


@fixture
async def provide_queue() -> AsyncGenerator[mariadb.Database]:
    """Two connections and primary-key ordering make contention reproducible."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(
        server.config(pool_size=2)
    ) as database:
        await database.migrate(
            {
                "001_jobs": "CREATE TABLE job (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    Job, [Job(id=1, status="pending"), Job(id=2, status="pending")]
                )
            )
        yield database


@test(mark="slow")
async def read_only_rejection_keeps_transaction_usable() -> None:
    """The policy guard runs before driver IO, rather than poisoning the connection."""
    database = await load_fixture(provide_queue())

    async with database.transaction(read_only=True) as transaction:
        with assert_raises(mariadb.TransactionStateError):
            await transaction.fetch_all(mariadb.select(Job).for_update())
        rows = await transaction.fetch_all(
            mariadb.select(Job.id).order_by(Job.id.asc())
        )
    assert_eq(rows, [1, 2])


@test(
    [
        Param(value="one", name="one"),
        Param(value="optional", name="optional"),
        Param(value="stream", name="stream"),
        Param(value="analyze", name="analyze"),
        Param(value="explain", name="explain"),
    ],
    mark="slow",
)
async def every_execution_path_checks_read_only_before_io(operation: str) -> None:
    """Streaming and executing plan inspection obey the same transaction guard."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update()

    async with database.transaction(read_only=True) as transaction:
        with assert_raises(mariadb.TransactionStateError):
            if operation == "one":
                await transaction.fetch_one(query)
            elif operation == "optional":
                await transaction.fetch_one_or_none(query)
            elif operation == "analyze":
                await transaction.explain_analyze(query)
            elif operation == "explain":
                await transaction.explain(query)
            else:
                async with transaction.fetch_chunks(query, size=1):
                    pass
        rows = await transaction.fetch_all(
            mariadb.select(Job.id).order_by(Job.id.asc())
        )
    assert_eq(rows, [1, 2])


@test(mark="slow")
async def skip_locked_selects_next_available_row() -> None:
    """A competing transaction skips the held primary-key row without waiting."""
    database = await load_fixture(provide_queue())

    async with database.transaction() as holder:
        await holder.fetch_one(mariadb.select(Job).where(Job.id.eq(1)).for_update())
        async with database.transaction(timeout=0.5) as claimant:
            row = await claimant.fetch_one(
                mariadb.select(Job)
                .where(Job.id.gt(0))
                .order_by(Job.id.asc())
                .limit(1)
                .for_update(wait="skip_locked")
            )
    assert_eq(row.id, 2)


@test(mark="slow")
async def skip_locked_returns_none_when_every_row_is_held() -> None:
    """An empty claim is a normal optional result, not a lock error."""
    database = await load_fixture(provide_queue())

    async with database.transaction() as holder:
        await holder.fetch_all(mariadb.select(Job).for_update())
        async with database.transaction(timeout=0.5) as claimant:
            row = await claimant.fetch_one_or_none(
                mariadb.select(Job).limit(1).for_update(wait="skip_locked")
            )
    assert_eq(row, None)


@test(mark="slow")
async def nowait_reports_contention_without_driver_timeout() -> None:
    """NOWAIT is a server execution error, not an application deadline expiry."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update(wait="nowait")

    async with database.transaction() as holder:
        await holder.fetch_one(query)
        async with database.transaction(timeout=0.5) as contender:
            with assert_raises(mariadb.ExecutionError):
                await contender.fetch_one(query)
    async with database.transaction() as next_transaction:
        row = await next_transaction.fetch_one(query)
    assert_eq(row.id, 1)


@test(
    [Param(value="commit", name="commit"), Param(value="rollback", name="rollback")],
    mark="slow",
)
async def default_lock_wait_resumes_after_outer_exit(outcome: str) -> None:
    """Finishing a buffered fetch does not release its row lock."""
    database = await load_fixture(provide_queue())
    started = Event()
    acquired = Event()
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update()

    async def wait_for_row() -> None:
        async with database.transaction() as contender:
            started.set()
            await contender.fetch_one(query)
            acquired.set()

    with fail_after(5):
        async with create_task_group() as tasks:
            with (
                assert_raises(mariadb.ModelValidationError)
                if outcome == "rollback"
                else nullcontext()
            ):
                async with database.transaction() as holder:
                    await holder.fetch_one(query)
                    tasks.start_soon(wait_for_row)
                    await started.wait()
                    with move_on_after(0.1) as waiting:
                        await acquired.wait()
                    assert_eq(waiting.cancel_called, True)
                    if outcome == "rollback":
                        message = "abandon claim"
                        raise mariadb.ModelValidationError(message)
            await acquired.wait()


@test(mark="slow")
async def concurrent_claims_update_distinct_jobs() -> None:
    """Workers keep their selected row locked until its claim update commits."""
    database = await load_fixture(provide_queue())
    barrier = asyncio.Barrier(2)
    claimed: list[int] = []
    query = (
        mariadb.select(Job)
        .where(Job.id.gt(0), Job.status.eq("pending"))
        .order_by(Job.id.asc())
        .limit(1)
        .for_update(wait="skip_locked")
    )

    async def claim() -> None:
        async with database.transaction(isolation="read_committed") as transaction:
            row = await transaction.fetch_one_or_none(query)
            assert row is not None
            claimed.append(row.id)
            await barrier.wait()
            await transaction.execute(
                mariadb.update(Job)
                .where(Job.id.eq(row.id))
                .set(Job.status.to("claimed"))
            )

    with fail_after(5):
        async with create_task_group() as tasks:
            tasks.start_soon(claim)
            tasks.start_soon(claim)
    async with database.transaction() as transaction:
        pending = await transaction.fetch_one_or_none(query)
    assert_eq(sorted(claimed), [1, 2])
    assert_eq(pending, None)


@test(mark="slow")
async def lock_wait_deadline_discards_connection() -> None:
    """A timed-out lock request does not leave an unsafe connection in the pool."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update()

    async with database.transaction() as holder:
        await holder.fetch_one(query)
        async with database.transaction(timeout=0.03) as contender:
            with assert_raises(mariadb.DatabaseOperationTimeoutError):
                await contender.fetch_one(query)
            with assert_raises(mariadb.DatabaseRuntimeError):
                await contender.fetch_all(mariadb.select(Job))
    async with database.transaction() as next_transaction:
        row = await next_transaction.fetch_one(query)
    assert_eq(row.id, 1)


@test(mark="slow")
async def inherited_read_only_policy_rejects_locking() -> None:
    """The guard uses the active server transaction, not only requested options."""
    database = await load_fixture(provide_queue())
    async with database.transaction() as transaction:
        await transaction.execute(mariadb.raw("SET SESSION tx_read_only=1"))

    async with database.transaction() as transaction:
        with assert_raises(mariadb.TransactionStateError):
            await transaction.fetch_one(
                mariadb.select(Job).where(Job.id.eq(1)).for_update()
            )
        row = await transaction.fetch_one(mariadb.select(Job).where(Job.id.eq(1)))
    assert_eq(row.id, 1)


@test(mark="slow")
async def explicit_read_write_overrides_inherited_read_only_for_locks() -> None:
    """A session default does not override the current transaction's access mode."""
    database = await load_fixture(provide_queue())
    async with database.transaction() as transaction:
        await transaction.execute(mariadb.raw("SET SESSION tx_read_only=1"))

    async with database.transaction(read_only=False) as transaction:
        row = await transaction.fetch_one(
            mariadb.select(Job).where(Job.id.eq(1)).for_update()
        )
    assert_eq(row.id, 1)


@test(mark="slow")
async def explain_locking_select_can_hold_row_locks() -> None:
    """MariaDB's optimizer can lock a const-table row while explaining FOR UPDATE."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update(wait="nowait")

    async with database.transaction() as transaction:
        await transaction.explain(query)
        async with database.transaction(timeout=0.5) as contender:
            with assert_raises(mariadb.ExecutionError):
                await contender.fetch_one(query)
    async with database.transaction() as next_transaction:
        row = await next_transaction.fetch_one(query)
    assert_eq(row.id, 1)


@test(mark="slow")
async def locking_named_projection_preserves_result_contract() -> None:
    """Named decoding remains unchanged by the locking modifier."""
    database = await load_fixture(provide_queue())

    async with database.transaction() as transaction:
        row = await transaction.fetch_one(
            mariadb.select(Job)
            .where(Job.id.eq(1))
            .project(JobSummary, id=Job.id, status=Job.status)
            .for_update()
        )
    assert_eq(row, JobSummary(id=1, status="pending"))


@test(mark="medium")
async def unsupported_sqlite_lock_does_not_poison_transaction() -> None:
    """Unsupported SQL is rejected before touching the connection."""
    case = await load_fixture(provide_nested_case("sqlite"))

    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.fetch_all(sqlite.select(SQLiteEntry).for_update())
        await transaction.execute(sqlite.insert(SQLiteEntry(value=1)))


@test(
    [Param(value="native", name="native"), Param(value="anyio", name="anyio")],
    mark="slow",
)
async def cancelled_lock_wait_releases_pool_capacity(cancellation: str) -> None:
    """Interrupted lock IO is discarded so another caller can use the free pool slot."""
    database = await load_fixture(provide_queue())
    started = Event()
    scopes: list[CancelScope] = []
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update()

    async def wait_for_row() -> None:
        with CancelScope() as scope:
            scopes.append(scope)
            async with database.transaction() as contender:
                started.set()
                await contender.fetch_one(query)

    with fail_after(5):
        async with database.transaction() as holder:
            await holder.fetch_one(query)
            waiter = asyncio.create_task(wait_for_row())
            try:
                await started.wait()
                await sleep(0.05)
                assert_eq(waiter.done(), False)
                if cancellation == "native":
                    waiter.cancel()
                    with assert_raises(asyncio.CancelledError):
                        await waiter
                else:
                    scopes[0].cancel()
                    await waiter
                async with database.transaction(timeout=0.5) as replacement:
                    row = await replacement.fetch_one(
                        mariadb.select(Job)
                        .where(Job.id.eq(2))
                        .for_update(wait="nowait")
                    )
            finally:
                if not waiter.done():
                    waiter.cancel()
                    with suppress(asyncio.CancelledError):
                        await waiter
    assert_eq(row.id, 2)


@test(mark="slow")
async def closing_locking_stream_does_not_release_row_lock() -> None:
    """Cursor lifetime does not shorten the enclosing transaction's lock lifetime."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update(wait="nowait")

    async with database.transaction() as holder:
        async with holder.fetch_chunks(query, size=1) as stream:
            batch = await anext(stream)
        async with database.transaction(timeout=0.5) as contender:
            with assert_raises(mariadb.ExecutionError):
                await contender.fetch_one(query)
    assert_eq(batch[0].id, 1)


@test(mark="slow")
async def releasing_savepoint_does_not_release_row_lock() -> None:
    """A successful nested claim is not independently committed."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update(wait="nowait")

    async with database.transaction() as holder:
        async with holder.begin_nested():
            await holder.fetch_one(query)
        async with database.transaction(timeout=0.5) as contender:
            with assert_raises(mariadb.ExecutionError):
                await contender.fetch_one(query)
    async with database.transaction() as next_transaction:
        row = await next_transaction.fetch_one(query)
    assert_eq(row.id, 1)


@test(mark="slow")
async def analyze_locking_select_retains_native_locks() -> None:
    """Executing plan inspection uses the same lock ownership as ordinary reads."""
    database = await load_fixture(provide_queue())
    query = mariadb.select(Job).where(Job.id.eq(1)).for_update(wait="nowait")

    async with database.transaction() as holder:
        await holder.explain_analyze(query)
        async with database.transaction(timeout=0.5) as contender:
            with assert_raises(mariadb.ExecutionError):
                await contender.fetch_one(query)
