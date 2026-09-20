"""Pool observability through Database snapshots and public observer callbacks."""

from asyncio import CancelledError
from collections.abc import AsyncGenerator, Iterable
from contextvars import ContextVar
from dataclasses import FrozenInstanceError, replace
from gc import collect
from pathlib import Path
from typing import Any
from unittest.mock import patch
from warnings import catch_warnings

from aiomysql import Connection as MariaDBConnection
from aiomysql import Cursor as MariaDBCursor
from aiomysql import OperationalError as MariaDBOperationalError
from aiosqlite import Connection, Cursor
from anyio import (
    Event,
    TemporaryDirectory,
    create_task_group,
    sleep_forever,
    wait_all_tasks_blocked,
)
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import capture_snekql_logs, provide_mariadb_server


def _pool_observer(events: list[sqlite.TelemetryEvent]) -> sqlite.Observer:
    """Keep pool assertions independent of unrelated runtime measurements."""

    def record(event: sqlite.TelemetryEvent) -> None:
        if event.kind in ("pool_wait", "pool_checkout"):
            events.append(event)

    return record


@test(mark="medium")
async def sqlite_occupancy_tracks_transaction_lease() -> None:
    """Snapshots distinguish idle capacity from a checked-out transaction."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        before = database.pool_stats()
        async with database.transaction():
            during = database.pool_stats()
        after = database.pool_stats()

    assert_eq(
        [
            (item.capacity, item.occupied, item.waiters)
            for item in (before, during, after)
        ],
        [(1, 0, 0), (1, 1, 0), (1, 0, 0)],
    )


@test(mark="medium")
async def timed_out_waiter_is_counted() -> None:
    """A failed acquisition does not consume the occupied connection's slot."""
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:", acquire_timeout=0)
        ) as database,
        database.transaction(),
    ):
        with assert_raises(sqlite.PoolTimeoutError):
            async with database.transaction():
                pass
        snapshot = database.pool_stats()

    assert_eq(
        (snapshot.occupied, snapshot.waiters, snapshot.acquisition_failures),
        (1, 0, 1),
    )


@test(mark="medium")
async def cancelled_waiter_leaves_queue() -> None:
    """Cancellation is counted separately and does not release another lease."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:

        async def wait_for_connection() -> None:
            async with database.transaction():
                await sleep_forever()

        async with database.transaction():
            queued = database.pool_stats()
            async with create_task_group() as tasks:
                tasks.start_soon(wait_for_connection)
                await wait_all_tasks_blocked()
                queued = database.pool_stats()
                tasks.cancel_scope.cancel()
            cancelled = database.pool_stats()

    assert_eq(
        (
            queued.waiters,
            cancelled.waiters,
            cancelled.occupied,
            cancelled.acquisition_failures,
            cancelled.acquisition_cancellations,
        ),
        (1, 0, 1, 0, 1),
    )


@test(mark="medium")
async def discarded_connection_holds_capacity_until_close() -> None:
    """A detached physical close remains occupied even after Transaction exit."""
    original_execute = Connection.execute
    original_close = Connection.close
    closing = Event()
    allow_close = Event()

    async def blocked_execute(
        connection: Connection, sql: str, parameters: Iterable[Any] | None = None
    ) -> Cursor:
        if sql == "SELECT 42":
            await sleep_forever()
        return await original_execute(connection, sql, parameters)

    async def blocked_close(connection: Connection) -> None:
        closing.set()
        await allow_close.wait()
        await original_close(connection)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:", operation_timeout=0.01)
    ) as database:
        with (
            patch.object(Connection, "execute", blocked_execute),
            patch.object(Connection, "close", blocked_close),
        ):
            try:
                with assert_raises(sqlite.DatabaseOperationTimeoutError):
                    async with database.transaction() as transaction:
                        await transaction.execute(sqlite.raw("SELECT 42"))
                await closing.wait()
                snapshot = database.pool_stats()
            finally:
                allow_close.set()
                await database.close()
        closed = database.pool_stats()

    assert_eq(
        (
            snapshot.occupied,
            snapshot.discarded_connections,
            closed.occupied,
            closed.state,
        ),
        (1, 1, 0, "closed"),
    )


@test(mark="medium")
async def acquisition_reports_separate_phases() -> None:
    """Admission wait and connection setup have distinct paired observations."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=_pool_observer(events)
        ) as database,
        database.transaction(),
    ):
        pass

    assert_eq(
        [(event.kind, event.phase, event.outcome) for event in events],
        [
            ("pool_wait", "start", None),
            ("pool_wait", "finish", "success"),
            ("pool_checkout", "start", None),
            ("pool_checkout", "finish", "success"),
        ],
    )
    for start, finish in zip(events[::2], events[1::2], strict=True):
        assert_eq(start.operation_id, finish.operation_id)
        assert_eq(start.backend, "sqlite")
        assert start.duration_seconds is None
        assert finish.duration_seconds is not None and finish.duration_seconds >= 0


@test(mark="medium")
async def observer_failure_does_not_fail_acquisition() -> None:
    """Callback exceptions are counted without exposing their text or breaking work."""

    def observer(_event: sqlite.TelemetryEvent) -> None:
        if _event.kind not in ("pool_wait", "pool_checkout"):
            return
        message = "secret callback payload"
        raise sqlite.DatabaseRuntimeError(message)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(sqlite.raw("SELECT 1 AS number"))
        snapshot = database.pool_stats()

    assert_eq(rows, [{"number": 1}])
    assert_eq(snapshot.observer_failures, 4)


@test(mark="slow")
async def mariadb_probe_failure_counts_discard() -> None:
    """A checkout probe failure is both a failed acquisition and an unsafe discard."""
    server = await load_fixture(provide_mariadb_server())
    events: list[mariadb.TelemetryEvent] = []

    async def failed_ping(connection: MariaDBConnection, *, reconnect: bool) -> None:
        del connection, reconnect
        raise MariaDBOperationalError(2013, "secret probe payload")

    async with await mariadb.Database.initialize(
        replace(server.config(pool_size=1), health_check="checkout"),
        observer=_pool_observer(events),
    ) as database:
        with (
            patch.object(MariaDBConnection, "ping", failed_ping),
            assert_raises(mariadb.DatabaseRuntimeError),
        ):
            async with database.transaction():
                pass
        snapshot = database.pool_stats()
        async with database.transaction():
            recovered = database.pool_stats()

    assert_eq(
        (
            snapshot.occupied,
            snapshot.acquisition_failures,
            snapshot.discarded_connections,
            recovered.occupied,
        ),
        (0, 1, 1, 1),
    )
    assert_eq(
        [(event.kind, event.outcome) for event in events if event.phase == "finish"],
        [
            ("pool_wait", "success"),
            ("pool_checkout", "error"),
            ("pool_wait", "success"),
            ("pool_checkout", "success"),
        ],
    )


@test(mark="medium")
async def observer_context_changes_do_not_escape() -> None:
    """Observers can read request context but cannot overwrite the caller's context."""
    request = ContextVar("request", default="outside")
    observed: list[str] = []

    def observer(_event: sqlite.TelemetryEvent) -> None:
        if _event.kind in ("pool_wait", "pool_checkout"):
            observed.append(request.get())
        request.set("callback-local")

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        with request.set("request-context"):
            async with database.transaction():
                caller_context = request.get()

    assert_eq(observed, ["request-context"] * 4)
    assert_eq(caller_context, "request-context")


@test(mark="medium")
async def shared_observer_has_unambiguous_operation_ids() -> None:
    """One observer can pair overlapping operations from different databases."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=_pool_observer(events)
        ) as first,
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=_pool_observer(events)
        ) as second,
        first.transaction(),
        second.transaction(),
    ):
        pass

    started = [event.operation_id for event in events if event.phase == "start"]
    assert_eq(len(set(started)), len(started))


@test(mark="medium")
async def async_generator_observer_is_rejected() -> None:
    """Async generators are not synchronous callbacks, even before their first yield."""

    async def observer(_event: sqlite.TelemetryEvent) -> AsyncGenerator[None]:
        yield None

    with assert_raises(sqlite.DatabaseRuntimeError) as caught:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"),
            observer=observer,  # ty: ignore[invalid-argument-type]
        ):
            pass
    assert_eq(
        str(caught.exception), "observer must be a synchronous callable returning None"
    )


@test(mark="slow")
async def mariadb_setup_failure_counts_discard() -> None:
    """A new connection rejected during session setup never becomes reusable."""
    server = await load_fixture(provide_mariadb_server())
    execute = MariaDBCursor.execute

    async def rejected_setup(
        cursor: MariaDBCursor, query: str, args: Any = None
    ) -> Any:
        if query == "SELECT VERSION()":
            message = "secret configuration failure"
            raise MariaDBOperationalError(2013, message)
        return await execute(cursor, query, args)

    async with (
        await mariadb.Database.initialize(server.config(pool_size=2)) as database,
        database.transaction(),
    ):
        with (
            patch.object(MariaDBCursor, "execute", rejected_setup),
            assert_raises(mariadb.DatabaseRuntimeError),
        ):
            async with database.transaction():
                pass
        snapshot = database.pool_stats()

    assert_eq(
        (
            snapshot.occupied,
            snapshot.acquisition_failures,
            snapshot.discarded_connections,
        ),
        (1, 1, 1),
    )


@test(
    [
        Param(("pool_wait", "start"), name="wait-start"),
        Param(("pool_wait", "finish"), name="wait-finish"),
        Param(("pool_checkout", "start"), name="checkout-start"),
        Param(("pool_checkout", "finish"), name="checkout-finish"),
    ],
    mark="medium",
)
async def observer_cancellation_does_not_leak_capacity(stage: tuple[str, str]) -> None:
    """Process-control exceptions propagate without abandoning admission or sockets."""
    interrupted = False

    def observer(event: sqlite.TelemetryEvent) -> None:
        nonlocal interrupted
        if not interrupted and (event.kind, event.phase) == stage:
            interrupted = True
            raise CancelledError

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        with assert_raises(CancelledError):
            async with database.transaction():
                pass
        async with database.transaction():
            snapshot = database.pool_stats()

    assert_eq((snapshot.occupied, snapshot.acquisition_cancellations), (1, 1))


@test(mark="medium")
async def waiter_cancellation_retains_request_context() -> None:
    """A cancelled wait reports its caller's request, not another task's context."""
    request = ContextVar("request", default="outside")
    observations: list[tuple[sqlite.TelemetryEvent, str]] = []

    def observer(event: sqlite.TelemetryEvent) -> None:
        observations.append((event, request.get()))

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:

        async def wait_for_connection() -> None:
            with request.set("cancelled-request"):
                async with database.transaction():
                    await sleep_forever()

        async with database.transaction(), create_task_group() as tasks:
            tasks.start_soon(wait_for_connection)
            await wait_all_tasks_blocked()
            tasks.cancel_scope.cancel()

    assert_eq(
        [
            (event.kind, context)
            for event, context in observations
            if event.phase == "finish" and event.outcome == "cancelled"
        ],
        [("pool_wait", "cancelled-request")],
    )


@test(mark="medium")
async def ordinary_observer_failures_are_not_logged() -> None:
    """Neither callback exception text nor traceback is sent to normal logging."""

    def observer(_event: sqlite.TelemetryEvent) -> None:
        if _event.kind not in ("pool_wait", "pool_checkout"):
            return
        message = "secret callback payload"
        raise sqlite.DatabaseRuntimeError(message)

    with capture_snekql_logs() as logs:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database:
            async with database.transaction():
                pass

    assert all(record.exc_info is None for record in logs.records)
    assert all(
        "secret callback payload" not in record.getMessage() for record in logs.records
    )


@test(mark="medium")
async def snapshots_are_immutable() -> None:
    """A saved observation cannot be rewritten as pool state changes."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:")
    ) as database:
        snapshot = database.pool_stats()
        with assert_raises(FrozenInstanceError):
            snapshot.occupied = 99  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def events_are_immutable() -> None:
    """Observers cannot mutate an event's measurement or classification."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=_pool_observer(events)
        ) as database,
        database.transaction(),
    ):
        pass
    with assert_raises(FrozenInstanceError):
        events[0].backend = "mariadb"  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def coroutine_return_is_closed_without_running() -> None:
    """A wrongly wrapped async callback does not leak an unawaited coroutine."""
    executed: list[bool] = []

    async def asynchronous_callback() -> None:
        executed.append(True)

    def observer(_event: sqlite.TelemetryEvent) -> Any:
        if _event.kind in ("pool_wait", "pool_checkout"):
            return asynchronous_callback()
        return None

    with catch_warnings(record=True) as warnings:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database:
            async with database.transaction():
                pass
            snapshot = database.pool_stats()
        collect()

    assert_eq((executed, warnings, snapshot.observer_failures), ([], [], 4))


@test(mark="medium")
async def waiting_acquisition_keeps_start_log() -> None:
    """Existing acquisition-start logging still includes attempts that time out."""
    with capture_snekql_logs() as logs:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:")
        ) as database:
            async with database.transaction():
                with assert_raises(sqlite.PoolTimeoutError):
                    async with database.transaction(timeout=0):
                        pass
    assert_eq(
        sum(
            "connection acquisition started" in record.getMessage()
            for record in logs.records
        ),
        2,
    )


@test(mark="slow")
async def mariadb_wait_timeout_has_no_checkout_event() -> None:
    """Timeout while queued never claims a second connection or reports setup."""
    server = await load_fixture(provide_mariadb_server())
    events: list[mariadb.TelemetryEvent] = []
    async with (
        await mariadb.Database.initialize(
            server.config(pool_size=1), observer=_pool_observer(events)
        ) as database,
        database.transaction(),
    ):
        events.clear()
        with assert_raises(mariadb.PoolTimeoutError):
            async with database.transaction(timeout=0):
                pass
        snapshot = database.pool_stats()

    assert_eq(
        [(event.kind, event.phase, event.outcome) for event in events],
        [("pool_wait", "start", None), ("pool_wait", "finish", "error")],
    )
    assert_eq(
        (
            snapshot.capacity,
            snapshot.occupied,
            snapshot.waiters,
            snapshot.acquisition_failures,
        ),
        (1, 1, 0, 1),
    )


@test(mark="slow")
async def mariadb_wait_cancellation_releases_ticket() -> None:
    """MariaDB reports cancelled admission independently from failed acquisitions."""
    server = await load_fixture(provide_mariadb_server())
    events: list[mariadb.TelemetryEvent] = []
    async with await mariadb.Database.initialize(
        server.config(pool_size=1), observer=_pool_observer(events)
    ) as database:

        async def wait_for_connection() -> None:
            async with database.transaction():
                await sleep_forever()

        async with database.transaction():
            queued = database.pool_stats()
            async with create_task_group() as tasks:
                tasks.start_soon(wait_for_connection)
                await wait_all_tasks_blocked()
                queued = database.pool_stats()
                tasks.cancel_scope.cancel()
            snapshot = database.pool_stats()

    assert_eq(
        (
            queued.waiters,
            snapshot.waiters,
            snapshot.occupied,
            snapshot.acquisition_cancellations,
            snapshot.acquisition_failures,
        ),
        (1, 0, 1, 1, 0),
    )
    assert_eq(
        [
            (event.backend, event.kind)
            for event in events
            if event.outcome == "cancelled"
        ],
        [("mariadb", "pool_wait")],
    )


@test(mark="medium")
async def default_pool_statistics_survive_close() -> None:
    """Statistics work without an observer and distinguish closed from available."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        before = database.pool_stats()
    after = database.pool_stats()
    assert_eq(
        (before.state, after.state, after.occupied, after.discarded_connections),
        ("open", "closed", 0, 0),
    )


@test(mark="medium")
async def acquisition_events_do_not_contain_database_path() -> None:
    """Connection metadata is excluded independently of diagnostic value visibility."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        TemporaryDirectory() as directory,
        await sqlite.Database.initialize(
            sqlite.Config(
                database=Path(directory) / "secret-database-name.sqlite",
                parameter_visibility="values",
            ),
            observer=_pool_observer(events),
        ) as database,
        database.transaction(),
    ):
        pass
    assert "secret-database-name" not in repr(events)
    assert directory not in repr(events)


@test(mark="medium")
async def async_callable_observer_is_rejected() -> None:
    """Async callable instances are rejected before a database is returned."""

    class Observer:
        async def __call__(self, _event: sqlite.TelemetryEvent) -> None:
            pass

    with assert_raises(sqlite.DatabaseRuntimeError):
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"),
            observer=Observer(),  # ty: ignore[invalid-argument-type]
        ):
            pass


@test(
    [
        Param(("pool_wait", "start"), name="wait-start"),
        Param(("pool_wait", "finish"), name="wait-finish"),
        Param(("pool_checkout", "start"), name="checkout-start"),
        Param(("pool_checkout", "finish"), name="checkout-finish"),
    ],
    mark="slow",
)
async def mariadb_observer_cancellation_preserves_capacity(
    stage: tuple[str, str],
) -> None:
    """A callback interruption cannot leave the driver's socket checked out."""
    server = await load_fixture(provide_mariadb_server())
    interrupted = False

    def observer(event: mariadb.TelemetryEvent) -> None:
        nonlocal interrupted
        if not interrupted and (event.kind, event.phase) == stage:
            interrupted = True
            raise CancelledError

    async with await mariadb.Database.initialize(
        server.config(pool_size=1), observer=observer
    ) as database:
        with assert_raises(CancelledError):
            async with database.transaction():
                pass
        async with database.transaction():
            snapshot = database.pool_stats()

    assert_eq((snapshot.occupied, snapshot.acquisition_cancellations), (1, 1))


@test(mark="medium")
async def interrupted_start_has_cancelled_finish() -> None:
    """Even cancellation from a start callback leaves a paired terminal event."""
    events: list[sqlite.TelemetryEvent] = []

    def observer(event: sqlite.TelemetryEvent) -> None:
        events.append(event)
        if event.phase == "start":
            raise CancelledError

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        with assert_raises(CancelledError):
            async with database.transaction():
                pass

    assert_eq(
        [(event.phase, event.outcome) for event in events],
        [("start", None), ("finish", "cancelled")],
    )
    assert_eq(events[0].operation_id, events[1].operation_id)
