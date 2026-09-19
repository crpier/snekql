"""Nested transaction contexts share their outer Transaction's connection."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, assert_type

from anyio import CancelScope, lowlevel
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.helpers import provide_mariadb_server
from tests.runtime.test_raw_execution import RawCase
from tests.runtime.test_raw_lifecycle import provide_contended_case


@fixture
async def provide_nested_case(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    """A single-connection database makes accidental acquisition observable."""
    if backend == "mariadb":
        server = await load_fixture(provide_mariadb_server())
        case = RawCase(
            await mariadb.Database.initialize(server.config(pool_size=1)), mariadb
        )
    else:
        case = RawCase(
            await sqlite.Database.initialize(database=":memory:", pool_size=1), sqlite
        )
    async with case.database:
        await case.database.migrate(
            {"001_entries": "CREATE TABLE nested_entries (value INTEGER PRIMARY KEY)"}
        )
        yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_success_commits_with_outer_transaction(backend: BackendFamily) -> None:
    """Nested writes use the sole checked-out connection and survive outer commit."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction(timeout=1) as transaction:  # noqa: SIM117 - keep transaction nesting explicit
        async with transaction.begin_nested():
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries")
        )
    assert_eq(rows, [{"value": 1}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_context_is_single_use(backend: BackendFamily) -> None:
    """A completed context cannot silently create a second savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        nested = transaction.begin_nested()
        async with nested:
            pass
        with assert_raises(case.namespace.TransactionReuseError):
            async with nested:
                pass


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_work_rejects_other_tasks(backend: BackendFamily) -> None:
    """A different task cannot accidentally write inside another task's savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:  # noqa: SIM117 - keep transaction nesting explicit
        async with transaction.begin_nested():
            with assert_raises(case.namespace.TransactionStateError):
                await asyncio.create_task(
                    transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                    )
                )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_exception_preserves_outer_writes(backend: BackendFamily) -> None:
    """Application failure rolls back only work since the savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        with assert_raises(case.namespace.ModelValidationError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                )
                failure = "application rejected work"
                raise case.namespace.ModelValidationError(failure)
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (3)")
        )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 3}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def released_savepoint_does_not_commit(backend: BackendFamily) -> None:
    """An outer rollback also undoes a successfully released savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    with assert_raises(case.namespace.ModelValidationError):
        async with case.database.transaction() as transaction:
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                )
            failure = "outer failure"
            raise case.namespace.ModelValidationError(failure)

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries")
        )
    assert_eq(rows, [])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_contexts_require_stack_order(backend: BackendFamily) -> None:
    """Out-of-order exits fail before releasing another active savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        outer = transaction.begin_nested()
        inner = transaction.begin_nested()
        await outer.__aenter__()
        await inner.__aenter__()
        with assert_raises(case.namespace.TransactionStateError):
            await outer.__aexit__(None, None, None)
        await inner.__aexit__(None, None, None)
        await outer.__aexit__(None, None, None)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_entry_rejects_open_stream(backend: BackendFamily) -> None:
    """A stream cannot hold the connection across savepoint creation."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:  # noqa: SIM117 - keep transaction nesting explicit
        async with transaction.fetch_chunks(
            case.namespace.raw("SELECT 1 AS value"), size=1
        ):
            with assert_raises(case.namespace.TransactionStateError):
                async with transaction.begin_nested():
                    pass


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_exit_rejects_open_stream(backend: BackendFamily) -> None:
    """The owner closes its cursor before releasing or rolling back a savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        nested = transaction.begin_nested()
        await nested.__aenter__()
        async with transaction.fetch_chunks(
            case.namespace.raw("SELECT 1 AS value"), size=1
        ):
            with assert_raises(case.namespace.TransactionStateError):
                await nested.__aexit__(None, None, None)
        await nested.__aexit__(None, None, None)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def outer_exit_refuses_unfinished_savepoint(backend: BackendFamily) -> None:
    """Malformed nesting must never turn unclosed nested work into a commit."""
    case = await load_fixture(provide_nested_case(backend))

    transaction = case.database.transaction()
    await transaction.__aenter__()
    nested = transaction.begin_nested()
    await nested.__aenter__()
    with assert_raises(case.namespace.TransactionStateError):
        await transaction.__aexit__(None, None, None)
    with assert_raises(case.namespace.TransactionClosedError):
        await transaction.execute(case.namespace.raw("SELECT 1"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_cleanup_failure_preserves_application_error(
    backend: BackendFamily,
) -> None:
    """Lost server savepoints cannot replace the application's pending exception."""
    case = await load_fixture(provide_nested_case(backend))
    failure = case.namespace.ModelValidationError("application failure")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.ModelValidationError) as caught:
            async with transaction.begin_nested():
                # Deliberate raw transaction misuse simulates lost server state.
                await transaction.execute(case.namespace.raw("ROLLBACK"))
                raise failure
        assert_eq(caught.exception, failure)
        with assert_raises(case.namespace.DatabaseRuntimeError):
            await transaction.execute(case.namespace.raw("SELECT 1"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_release_failure_raises_domain_error(backend: BackendFamily) -> None:
    """A clean body must report failed release instead of pretending to succeed."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.DatabaseRuntimeError):
            async with transaction.begin_nested():
                await transaction.execute(case.namespace.raw("ROLLBACK"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def inner_rollback_preserves_enclosing_savepoint(backend: BackendFamily) -> None:
    """A caught inner failure leaves the enclosing savepoint usable."""
    case = await load_fixture(provide_nested_case(backend))
    failure = case.namespace.ModelValidationError("inner failure")

    async with case.database.transaction() as transaction:  # noqa: SIM117 - keep transaction nesting explicit
        async with transaction.begin_nested():
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )
            with assert_raises(case.namespace.ModelValidationError):
                async with transaction.begin_nested():
                    await transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                    )
                    raise failure
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (3)")
            )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 3}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def cancellation_between_operations_rolls_back_nested_work(
    backend: BackendFamily,
) -> None:
    """Shielded cleanup preserves earlier writes when no driver call was interrupted."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        with CancelScope() as cancellation:
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                )
                cancellation.cancel()
                await lowlevel.checkpoint()
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (3)")
        )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 3}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_driver_failure_remains_terminal(backend: BackendFamily) -> None:
    """A savepoint must not revive a connection after an unclassified driver error."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("SELECT * FROM missing_nested_table")
                )
        with assert_raises(case.namespace.DatabaseRuntimeError):
            await transaction.execute(case.namespace.raw("SELECT 1"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_entry_requires_started_transaction(backend: BackendFamily) -> None:
    """Constructing a context does not implicitly begin its outer Transaction."""
    case = await load_fixture(provide_nested_case(backend))

    with assert_raises(case.namespace.TransactionNotStartedError):
        async with case.database.transaction().begin_nested():
            pass


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_entry_rejects_closed_transaction(backend: BackendFamily) -> None:
    """An old transaction cannot be restarted by creating a savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        pass
    with assert_raises(case.namespace.TransactionClosedError):
        async with transaction.begin_nested():
            pass


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_exit_is_single_use(backend: BackendFamily) -> None:
    """A repeated exit cannot pop or release another context."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        nested = transaction.begin_nested()
        async with nested:
            pass
        with assert_raises(case.namespace.TransactionStateError):
            await nested.__aexit__(None, None, None)


if TYPE_CHECKING:

    async def nested_sqlite_helper(transaction: sqlite.Transaction) -> None:
        """The context does not replace the original backend-typed Transaction."""
        assert_type(transaction.begin_nested(), AbstractAsyncContextManager[None])
        async with transaction.begin_nested() as context:
            assert_type(context, None)
            await transaction.execute(sqlite.raw("SELECT 1"))
            await transaction.execute(mariadb.raw("SELECT 1"))  # ty: ignore[no-matching-overload]

    async def nested_mariadb_helper(transaction: mariadb.Transaction) -> None:
        """MariaDB exposes the same context without widening transaction typing."""
        assert_type(transaction.begin_nested(), AbstractAsyncContextManager[None])
        async with transaction.begin_nested() as context:
            assert_type(context, None)
            await transaction.execute(mariadb.raw("SELECT 1"))
            await transaction.execute(sqlite.raw("SELECT 1"))  # ty: ignore[no-matching-overload]


@test(mark="medium")
async def nested_typed_stream_rejects_cross_task_consumption() -> None:
    """Builder streams obey the savepoint owner just like buffered queries."""
    case = await load_fixture(provide_nested_case("sqlite"))

    class NestedEntries[S = sqlite.Pending](
        sqlite.Model[S, "NestedEntries[sqlite.Fetched]"]
    ):
        value: NestedEntries.Col[int] = sqlite.Integer(primary_key=True)

    async with case.database.transaction() as transaction:  # noqa: SIM117 - keep transaction nesting explicit
        async with transaction.begin_nested():
            async with transaction.fetch_chunks(
                sqlite.select(NestedEntries).all(), size=1
            ) as stream:
                with assert_raises(sqlite.TransactionStateError):
                    await asyncio.create_task(anext(stream))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_driver_timeout_cannot_be_recovered(backend: BackendFamily) -> None:
    """A timed-out driver call stays fatal even when a savepoint existed."""
    case = await load_fixture(provide_contended_case(backend))

    async with case.database.transaction() as owner:
        await owner.execute(
            case.namespace.raw("UPDATE raw_entries SET value=2 WHERE value=1")
        )
        async with case.database.transaction(timeout=0.03) as waiter:
            with assert_raises(case.namespace.DatabaseOperationTimeoutError):
                async with waiter.begin_nested():
                    await waiter.execute(
                        case.namespace.raw("UPDATE raw_entries SET value=3")
                    )
            with assert_raises(case.namespace.DatabaseRuntimeError):
                await waiter.execute(case.namespace.raw("SELECT 1"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def native_cancellation_between_operations_rolls_back_nested_work(
    backend: BackendFamily,
) -> None:
    """Native task cancellation unwinds the savepoint without committing its writes."""
    case = await load_fixture(provide_nested_case(backend))

    async def work() -> None:
        async with case.database.transaction() as transaction:
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )
            with assert_raises(asyncio.CancelledError):
                async with transaction.begin_nested():
                    await transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                    )
                    task = asyncio.current_task()
                    assert task is not None
                    task.cancel()
                    await asyncio.sleep(0)
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (3)")
            )

    await asyncio.create_task(work())
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 3}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def database_transaction_nesting_still_acquires_independently(
    backend: BackendFamily,
) -> None:
    """Only begin_nested reuses the checked-out connection when pool_size is one."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction():
        with assert_raises(case.namespace.PoolTimeoutError):
            async with case.database.transaction(timeout=0.02):
                pass
