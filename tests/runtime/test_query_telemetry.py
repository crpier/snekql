"""Query measurements through execution, observers, and compiled inspection."""

from asyncio import CancelledError, create_task
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar
from unittest.mock import patch

from aiomysql import Cursor as MariaDBCursor
from aiosqlite import Connection, Cursor
from anyio import Event, create_task_group, sleep_forever, wait_all_tasks_blocked
from pydantic import BeforeValidator
from snektest import Param, assert_eq, assert_ne, assert_raises, load_fixture, test

from snekql import sqlite
from snekql.model import BackendFamily
from tests.runtime.test_raw_execution import provide_raw_case


@test(mark="fast")
def fingerprint_excludes_bindings() -> None:
    """The same parameterized statement has one fingerprint across bound values."""
    first = sqlite.CompiledQuery(
        backend="sqlite", sql="SELECT ?", params=("secret-one",)
    )
    second = sqlite.CompiledQuery(
        backend="sqlite", sql="SELECT ?", params=("secret-two",)
    )
    different = sqlite.CompiledQuery(backend="sqlite", sql="SELECT ?, ?", params=(1, 2))
    assert_eq(first.fingerprint, second.fingerprint)
    assert_ne(first.fingerprint, different.fingerprint)
    assert "secret" not in first.fingerprint


@test(mark="medium")
async def buffered_query_reports_driver_then_materialization() -> None:
    """Buffered native work finishes before cardinality and row conversion begin."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
    ):
        events.clear()
        await transaction.fetch_one(sqlite.raw("SELECT 1 AS number"))
        recorded = tuple(events)

    assert_eq(
        [(event.kind, event.phase) for event in recorded],
        [
            ("driver", "start"),
            ("driver", "finish"),
            ("materialization", "start"),
            ("materialization", "finish"),
        ],
    )
    assert_eq([event.fingerprint for event in recorded], ["raw"] * 4)


@test(
    [
        Param("fetch_all", name="all"),
        Param("fetch_one_or_none", name="optional"),
        Param("execute", name="execute"),
    ],
    mark="medium",
)
async def buffered_result_policies_are_measured(operation: str) -> None:
    """Every buffered result policy gets a materialization measurement."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
    ):
        events.clear()
        sql = (
            "CREATE TABLE measured (number INTEGER)"
            if operation == "execute"
            else "SELECT 1 AS number"
        )
        await getattr(transaction, operation)(sqlite.raw(sql))
        recorded = tuple(events)

    assert_eq(
        [(event.kind, event.outcome) for event in recorded if event.phase == "finish"],
        [("driver", "success"), ("materialization", "success")],
    )


@test(mark="medium")
async def explain_packaging_is_measured() -> None:
    """Inspection results have a packaging phase separate from optimizer I/O."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        number: sqlite.Col[int] = sqlite.Integer()

    events: list[sqlite.TelemetryEvent] = []
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=events.append
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            events.clear()
            await transaction.explain(sqlite.select(Entry.number))
            recorded = tuple(events)

    assert_eq(
        [(event.kind, event.outcome) for event in recorded if event.phase == "finish"],
        [("driver", "success"), ("materialization", "success")],
    )


@test(mark="medium")
async def stream_batches_have_materialization_events() -> None:
    """Each delivered batch measures its conversion independently of its fetch."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
        transaction.fetch_chunks(
            sqlite.raw("SELECT 1 AS number UNION ALL SELECT 2"), size=1
        ) as stream,
    ):
        events.clear()
        await anext(stream)
        first = tuple(events)
        events.clear()
        await anext(stream)
        second = tuple(events)

    for batch in (first, second):
        assert_eq(
            [(event.kind, event.outcome) for event in batch if event.phase == "finish"],
            [("driver", "success"), ("materialization", "success")],
        )


@test(mark="medium")
async def stream_shape_failure_is_materialization_failure() -> None:
    """Valid SQL with unusable mapping columns must not be reported as a driver error."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
    ):
        events.clear()
        with assert_raises(sqlite.RawResultShapeError):
            async with transaction.fetch_chunks(
                sqlite.raw("SELECT 1 AS duplicate, 2 AS duplicate"), size=1
            ):
                pass
        recorded = tuple(events)

    failures = [
        (event.kind, event.outcome)
        for event in recorded
        if event.phase == "finish"
        and event.outcome == "error"
        and event.kind in ("driver", "materialization")
    ]
    assert failures
    assert all(kind == "materialization" for kind, _ in failures)


@test(mark="medium")
async def transaction_lifetime_ends_after_pool_return() -> None:
    """Transaction lifetime includes application work and terminal cleanup, not acquisition."""
    events: list[sqlite.TelemetryEvent] = []
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=events.append
    ) as database:
        async with database.transaction():
            starts = [event for event in events if event.kind == "transaction"]
        snapshot = database.pool_stats()

    lifetime = [event for event in events if event.kind == "transaction"]
    assert_eq([event.phase for event in starts], ["start"])
    assert_eq(
        [(event.phase, event.outcome) for event in lifetime],
        [("start", None), ("finish", "success")],
    )
    assert_eq(snapshot.occupied, 0)
    assert_eq(events[0].kind, "pool_wait")


@test(mark="medium")
async def stream_lifetime_covers_context_until_close() -> None:
    """Stream lifetime includes caller pauses and ends only after cursor cleanup."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
    ):
        async with transaction.fetch_chunks(
            sqlite.raw("SELECT 1 AS number"), size=1
        ) as stream:
            await anext(stream)
            active = [event.phase for event in events if event.kind == "stream"]
        completed = [event for event in events if event.kind == "stream"]

    assert_eq(active, ["start"])
    assert_eq(
        [(event.phase, event.outcome) for event in completed],
        [("start", None), ("finish", "success")],
    )
    assert_eq([event.fingerprint for event in completed], ["raw", "raw"])


@test(mark="medium")
async def transaction_control_has_driver_measurements() -> None:
    """BEGIN and COMMIT are driver work, without fabricated query fingerprints."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction(),
    ):
        pass
    driver = [event for event in events if event.kind == "driver"]
    assert_eq(
        [(event.phase, event.outcome, event.fingerprint) for event in driver],
        [("start", None, None), ("finish", "success", None)] * 2,
    )


@test(mark="medium")
async def stream_entry_reports_escaping_cleanup_cancellation() -> None:
    """A cleanup interruption superseding a shape error is reported as cancellation."""
    events: list[sqlite.TelemetryEvent] = []
    driver_starts = 0

    def observer(event: sqlite.TelemetryEvent) -> None:
        nonlocal driver_starts
        events.append(event)
        if (
            event.kind == "driver"
            and event.fingerprint == "raw"
            and event.phase == "start"
        ):
            driver_starts += 1
            if driver_starts == 2:
                raise CancelledError

    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database,
        database.transaction() as transaction,
    ):
        with assert_raises(CancelledError):
            async with transaction.fetch_chunks(
                sqlite.raw("SELECT 1 AS duplicate, 2 AS duplicate"), size=1
            ):
                pass
    assert_eq(
        [
            event.outcome
            for event in events
            if event.kind == "stream" and event.phase == "finish"
        ],
        ["cancelled"],
    )


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def validation_failure_is_not_driver_failure(backend: BackendFamily) -> None:
    """Bad decoded values report materialization errors without exposing input."""
    events: list[sqlite.TelemetryEvent] = []
    case = await load_fixture(provide_raw_case(backend, observer=events.append))

    @dataclass
    class Total:
        amount: int

    async with case.database.transaction() as transaction:
        events.clear()
        with assert_raises(sqlite.RawResultValidationError):
            await transaction.fetch_one(
                case.namespace.raw("SELECT 'secret-value' AS amount", validate=Total)
            )
        recorded = tuple(events)

    assert_eq(
        [(event.kind, event.outcome) for event in recorded if event.phase == "finish"],
        [("driver", "success"), ("materialization", "error")],
    )
    assert "secret-value" not in repr(events)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def driver_failure_has_no_materialization(backend: BackendFamily) -> None:
    """Failed native execution cannot fabricate a row-conversion measurement."""
    events: list[sqlite.TelemetryEvent] = []
    case = await load_fixture(provide_raw_case(backend, observer=events.append))
    with assert_raises(sqlite.ExecutionError):
        async with case.database.transaction() as transaction:
            events.clear()
            await transaction.fetch_one(
                case.namespace.raw("SELECT missing_secret_column")
            )

    assert_eq(
        [(event.kind, event.outcome) for event in events if event.phase == "finish"],
        [("driver", "error"), ("transaction", "error")],
    )
    assert "missing_secret_column" not in repr(events)


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def caught_unsafe_failure_is_not_successful_transaction(
    backend: BackendFamily,
) -> None:
    """An exit that silently discards unsafe work still reports a failed lifetime."""
    events: list[sqlite.TelemetryEvent] = []
    case = await load_fixture(provide_raw_case(backend, observer=events.append))
    async with case.database.transaction() as transaction:
        with assert_raises(sqlite.ExecutionError):
            await transaction.fetch_one(
                case.namespace.raw("SELECT missing_secret_column")
            )

    assert_eq(
        [
            event.outcome
            for event in events
            if event.kind == "transaction" and event.phase == "finish"
        ],
        ["error"],
    )
    assert_eq(transaction.commit_outcome, "not_attempted")


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def caught_stream_failure_marks_lifetime(backend: BackendFamily) -> None:
    """Handling a bad batch inside the stream does not report a clean stream."""
    events: list[sqlite.TelemetryEvent] = []
    case = await load_fixture(provide_raw_case(backend, observer=events.append))

    @dataclass
    class Total:
        amount: int

    async with (
        case.database.transaction() as transaction,
        transaction.fetch_chunks(
            case.namespace.raw("SELECT 'secret-value' AS amount", validate=Total),
            size=1,
        ) as stream,
    ):
        with assert_raises(sqlite.RawResultValidationError):
            await anext(stream)

    assert_eq(
        [
            event.outcome
            for event in events
            if event.kind == "stream" and event.phase == "finish"
        ],
        ["error"],
    )
    assert_eq(transaction.commit_outcome, "committed")


@test(mark="medium")
async def compiled_fingerprint_matches_builder_execution() -> None:
    """Applications can allowlist the same identifier that runtime events carry."""

    class Entry[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Entry[sqlite.Row]]]
        label: sqlite.Col[str] = sqlite.Text()

    events: list[sqlite.TelemetryEvent] = []
    query = sqlite.select(Entry.label).where(Entry.label.eq("secret-one"))
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=events.append
    ) as database:
        await database.migrate({"001": sqlite.scaffold([Entry])})
        async with database.transaction() as transaction:
            events.clear()
            await transaction.fetch_all(query)
            recorded = tuple(events)

    assert_eq(
        [event.fingerprint for event in recorded], [query.compile().fingerprint] * 4
    )
    assert "secret-one" not in repr(events)
    assert "label" not in repr(events)


@test(mark="fast")
def fingerprint_has_versioned_known_vector() -> None:
    """The identifier has an explicit format version and a fixed cross-run digest."""
    compiled = sqlite.CompiledQuery(backend="sqlite", sql="SELECT ?", params=())
    assert_eq(
        compiled.fingerprint,
        "v1:042e30b5e8a34aceb965eb25b01777b408a89da6463c0c36281a3fb0b98f4d32",
    )


@test(mark="fast")
def fingerprint_is_backend_specific() -> None:
    """Identical SQL spelling on different backends is not the same fingerprint."""
    first = sqlite.CompiledQuery(backend="sqlite", sql="SELECT 1", params=())
    second = sqlite.CompiledQuery(backend="mariadb", sql="SELECT 1", params=())
    assert_ne(first.fingerprint, second.fingerprint)


@test(mark="fast")
def fingerprint_never_formats_bound_objects() -> None:
    """Computing an identifier does not even call an application's parameter repr."""

    class Secret:
        def __repr__(self) -> str:
            message = "must not render a parameter"
            raise sqlite.DatabaseRuntimeError(message)

    compiled = sqlite.CompiledQuery(
        backend="sqlite", sql="SELECT ?", params=(Secret(),)
    )
    assert_eq(
        compiled.fingerprint,
        "v1:042e30b5e8a34aceb965eb25b01777b408a89da6463c0c36281a3fb0b98f4d32",
    )


@test(mark="medium")
async def competing_exit_cannot_finish_owners_measurement() -> None:
    """Cancelling a competing exit does not end the owner's in-flight commit span."""
    events: list[sqlite.TelemetryEvent] = []
    committing = Event()
    allow_commit = Event()
    execute = Connection.execute

    async def hold_commit(
        connection: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql == "COMMIT":
            committing.set()
            await allow_commit.wait()
        return await execute(connection, sql, parameters)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=events.append
    ) as database:
        transaction = await database.transaction().__aenter__()
        with patch.object(Connection, "execute", hold_commit):
            owner = create_task(transaction.__aexit__(None, None, None))
            await committing.wait()
            contender = create_task(transaction.__aexit__(None, None, None))
            await wait_all_tasks_blocked()
            contender.cancel()
            try:
                with assert_raises(CancelledError):
                    await contender
                premature = [
                    event.phase for event in events if event.kind == "transaction"
                ]
            finally:
                allow_commit.set()
                await owner

    assert_eq(premature, ["start"])
    assert_eq(
        [
            event.outcome
            for event in events
            if event.kind == "transaction" and event.phase == "finish"
        ],
        ["success"],
    )


@test(
    [
        Param(
            (kind, phase, streaming),
            name=f"{kind}-{phase}-{'streaming' if streaming else 'buffered'}",
        )
        for kind in ("transaction", "driver", "materialization", "stream")
        for phase in ("start", "finish")
        for streaming in ((True,) if kind == "stream" else (False, True))
    ],
    mark="medium",
)
async def interrupted_runtime_hook_preserves_cleanup(
    case: tuple[str, str, bool],
) -> None:
    """Callback cancellation cannot leak a transaction lease or stream cursor."""
    kind, phase, streaming = case
    interrupted = False

    def observer(event: sqlite.TelemetryEvent) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and event.kind == kind
            and event.phase == phase
            and (kind != "driver" or event.fingerprint == "raw")
        ):
            interrupted = True
            raise CancelledError

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        with assert_raises(CancelledError):
            async with database.transaction() as transaction:
                if streaming:
                    async with transaction.fetch_chunks(
                        sqlite.raw("SELECT 1 AS number"), size=1
                    ) as stream:
                        await anext(stream)
                else:
                    await transaction.fetch_one(sqlite.raw("SELECT 1 AS number"))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_one(sqlite.raw("SELECT 2 AS number"))
    assert_eq(rows, {"number": 2})


@test(mark="medium")
async def finished_transaction_callback_retains_commit_evidence() -> None:
    """A post-cleanup interruption must not turn an acknowledged commit into unknown."""

    def observer(event: sqlite.TelemetryEvent) -> None:
        if event.kind == "transaction" and event.phase == "finish":
            raise CancelledError

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        transaction = database.transaction()
        with assert_raises(CancelledError):
            async with transaction:
                pass
    assert_eq(transaction.commit_outcome, "committed")


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def cancelled_stream_retains_caller_context(backend: BackendFamily) -> None:
    """Cancellation closes stream and transaction measurements in request context."""
    request = ContextVar("request", default="outside")
    seen: list[tuple[sqlite.TelemetryEvent, str]] = []

    def observer(event: sqlite.TelemetryEvent) -> None:
        seen.append((event, request.get()))

    case = await load_fixture(provide_raw_case(backend, observer=observer))
    with request.set("cancelled-request"), assert_raises(CancelledError):
        async with (
            case.database.transaction() as transaction,
            transaction.fetch_chunks(case.namespace.raw("SELECT 1 AS number"), size=1),
        ):
            raise CancelledError

    assert_eq(
        [
            (event.kind, context)
            for event, context in seen
            if event.phase == "finish" and event.outcome == "cancelled"
        ],
        [("stream", "cancelled-request"), ("transaction", "cancelled-request")],
    )


@test(mark="medium")
async def validation_runs_outside_driver_measurement() -> None:
    """The public validator runs inside materialization, never inside native timing."""
    events: list[sqlite.TelemetryEvent] = []
    during_validation: list[set[str]] = []

    def validate(value: object) -> object:
        finished = {event.operation_id for event in events if event.phase == "finish"}
        during_validation.append(
            {
                event.kind
                for event in events
                if event.phase == "start" and event.operation_id not in finished
            }
        )
        return value

    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
    ):
        await transaction.fetch_one(
            sqlite.raw(
                "SELECT 1 AS number",
                validate=Annotated[object, BeforeValidator(validate)],
            )
        )

    assert_eq(during_validation, [{"transaction", "materialization"}])


@test(mark="medium")
async def caller_work_is_outside_driver_measurement() -> None:
    """Only lifetime measurements remain active while the caller holds a batch."""
    events: list[sqlite.TelemetryEvent] = []
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=events.append
        ) as database,
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.raw("SELECT 1 AS number"), size=1) as stream,
    ):
        await anext(stream)
        finished = {event.operation_id for event in events if event.phase == "finish"}
        active = {
            event.kind
            for event in events
            if event.phase == "start" and event.operation_id not in finished
        }
    assert_eq(active, {"transaction", "stream"})


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def driver_cancellation_retains_request_context(backend: BackendFamily) -> None:
    """In-flight driver cancellation keeps caller context through rollback/discard."""
    request = ContextVar("request", default="outside")
    seen: list[tuple[sqlite.TelemetryEvent, str]] = []

    def observer(event: sqlite.TelemetryEvent) -> None:
        seen.append((event, request.get()))

    case = await load_fixture(provide_raw_case(backend, observer=observer))
    entered = Event()
    sqlite_execute = Connection.execute
    mariadb_execute = MariaDBCursor.execute

    async def block_sqlite(
        connection: Connection, sql: str, parameters: Iterable[object] | None = None
    ) -> Cursor:
        if sql == "SELECT 42 AS number":
            entered.set()
            await sleep_forever()
        return await sqlite_execute(connection, sql, parameters)

    async def block_mariadb(cursor: MariaDBCursor, query: str, args: Any = None) -> Any:
        if query == "SELECT 42 AS number":
            entered.set()
            await sleep_forever()
        return await mariadb_execute(cursor, query, args)

    async def read() -> None:
        with request.set("driver-request"):
            async with case.database.transaction() as transaction:
                await transaction.fetch_one(case.namespace.raw("SELECT 42 AS number"))

    with (
        patch.object(Connection, "execute", block_sqlite),
        patch.object(MariaDBCursor, "execute", block_mariadb),
    ):
        async with create_task_group() as tasks:
            tasks.start_soon(read)
            await entered.wait()
            tasks.cancel_scope.cancel()

    assert_eq(
        [
            (event.kind, context)
            for event, context in seen
            if event.phase == "finish" and event.outcome == "cancelled"
        ],
        [("driver", "driver-request"), ("transaction", "driver-request")],
    )


@test(mark="medium")
async def runtime_observer_failure_does_not_change_results() -> None:
    """Ordinary runtime hook failures remain telemetry failures, not database errors."""

    def observer(event: sqlite.TelemetryEvent) -> None:
        if event.kind not in ("pool_wait", "pool_checkout"):
            message = "private observer payload"
            raise sqlite.DatabaseRuntimeError(message)

    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"), observer=observer
    ) as database:
        async with database.transaction() as transaction:
            row = await transaction.fetch_one(sqlite.raw("SELECT 1 AS number"))
        failures = database.pool_stats().observer_failures
    assert_eq(row, {"number": 1})
    assert_eq(failures, 10)
