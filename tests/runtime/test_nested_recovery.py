"""Savepoint recovery is limited to completed, recognized constraint errors."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from io import StringIO
from traceback import format_exception
from typing import ClassVar

from anyio import fail_after
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from tests.runtime.test_nested_transactions import provide_nested_case
from tests.runtime.test_raw_execution import RawCase
from tests.runtime.test_raw_lifecycle import provide_contended_case


class SQLiteEntry[S = sqlite.Pending](sqlite.Model[S]):
    """Builder projection of the same physical table used by raw recovery tests."""

    __row_type__: ClassVar[sqlite.ReadType[SQLiteEntry[sqlite.Row]]]

    __tablename__: ClassVar[str] = "nested_entries"
    value: SQLiteEntry.Col[int] = sqlite.Integer(primary_key=True)


class MariaEntry[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB's typed write path must retain the same recovery guarantees."""

    __row_type__: ClassVar[mariadb.ReadType[MariaEntry[mariadb.Row]]]

    __tablename__: ClassVar[str] = "nested_entries"
    value: MariaEntry.Col[int] = mariadb.Integer(primary_key=True)


@fixture
async def provide_constraint_case(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    """Distinct constraint domains exercise adapter classification on real servers."""
    case = await load_fixture(provide_nested_case(backend))
    await case.database.migrate(
        {
            "001_entries": "CREATE TABLE nested_entries (value INTEGER PRIMARY KEY)",
            "002_constraints": """CREATE TABLE constrained_entries (
            value INTEGER PRIMARY KEY,
            label VARCHAR(40) NOT NULL UNIQUE,
            positive INTEGER NOT NULL CHECK (positive > 0),
            parent INTEGER NOT NULL,
            FOREIGN KEY (parent) REFERENCES nested_entries(value)
        )""",
        }
    )
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        await transaction.execute(
            case.namespace.raw(
                "INSERT INTO constrained_entries VALUES (1, 'existing', 1, 1)"
            )
        )
    yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def nested_duplicate_recovers_after_rollback(backend: BackendFamily) -> None:
    """A duplicate key rolls back the nested writes and preserves outer work."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                )
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                )
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
async def caught_constraint_requires_nested_rollback(backend: BackendFamily) -> None:
    """Swallowing the driver error cannot silently release partially completed work."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.TransactionStateError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                )
                with assert_raises(case.namespace.ExecutionError):
                    await transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                    )
                with assert_raises(case.namespace.TransactionStateError):
                    await transaction.execute(case.namespace.raw("SELECT 1"))
                with assert_raises(case.namespace.TransactionStateError):
                    async with transaction.begin_nested():
                        pass
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
        )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries")
        )
    assert_eq(rows, [{"value": 2}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(
            value="INSERT INTO constrained_entries VALUES (3, 'existing', 1, 1)",
            name="unique",
        ),
        Param(
            value="INSERT INTO constrained_entries VALUES (3, NULL, 1, 1)",
            name="not_null",
        ),
        Param(
            value="INSERT INTO constrained_entries VALUES (3, 'check', 0, 1)",
            name="check",
        ),
        Param(
            value="INSERT INTO constrained_entries VALUES (3, 'missing_parent', 1, 99)",
            name="foreign_key_insert",
        ),
        Param(
            value="DELETE FROM nested_entries WHERE value=1", name="foreign_key_delete"
        ),
    ],
    mark="slow",
)
async def recognized_constraints_preserve_outer_transaction(
    backend: BackendFamily, sql: str
) -> None:
    """Rollback removes every write in the failed nested scope, not just the bad row."""
    case = await load_fixture(provide_constraint_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw(
                        "INSERT INTO constrained_entries VALUES (2, 'temporary', 1, 1)"
                    )
                )
                await transaction.execute(case.namespace.raw(sql))
        await transaction.execute(
            case.namespace.raw(
                "INSERT INTO constrained_entries VALUES (4, 'retained', 1, 1)"
            )
        )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM constrained_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 4}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def builder_duplicate_recovers_after_rollback(backend: BackendFamily) -> None:
    """Typed builder statements retain original driver errors and allow safe recovery."""
    case = await load_fixture(provide_nested_case(backend))
    entry = SQLiteEntry if backend == "sqlite" else MariaEntry

    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.insert(entry(value=1)))
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(case.namespace.insert(entry(value=2)))
                await transaction.execute(case.namespace.insert(entry(value=1)))
        await transaction.execute(case.namespace.insert(entry(value=3)))

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.select(entry.value).all().order_by(entry.value.asc())
        )
    assert_eq(rows, [1, 3])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def constraint_without_savepoint_remains_terminal(backend: BackendFamily) -> None:
    """Recognizing a driver error does not change the ordinary Transaction contract."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        with assert_raises(case.namespace.ExecutionError):
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
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
async def failed_inner_savepoint_preserves_enclosing_scope(
    backend: BackendFamily,
) -> None:
    """Constraint recovery belongs to the innermost savepoint, not the whole stack."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:  # noqa: SIM117 - show savepoint nesting
        async with transaction.begin_nested():
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )
            with assert_raises(case.namespace.ExecutionError):
                async with transaction.begin_nested():
                    await transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
                    )
                    await transaction.execute(
                        case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                    )
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
async def stream_open_constraint_recovers_on_exit(backend: BackendFamily) -> None:
    """An error before result metadata opens no stream cursor that could block rollback."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                async with transaction.fetch_chunks(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)"),
                    size=1,
                ):
                    pass
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (2)")
        )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 2}])


@test(mark="medium")
async def sqlite_rollback_conflict_cannot_be_recovered() -> None:
    """A constraint policy that ends the whole transaction is not statement-local."""
    case = await load_fixture(provide_nested_case("sqlite"))

    async with case.database.transaction() as transaction:
        await transaction.execute(sqlite.raw("INSERT INTO nested_entries VALUES (1)"))
        with assert_raises(sqlite.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    sqlite.raw("INSERT OR ROLLBACK INTO nested_entries VALUES (1)")
                )
        with assert_raises(sqlite.DatabaseRuntimeError):
            await transaction.execute(sqlite.raw("SELECT 1"))


@test(mark="slow")
async def mariadb_deadlock_cannot_be_recovered_by_savepoint() -> None:
    """The deadlock victim loses its outer transaction, not just one statement."""
    case = await load_fixture(provide_contended_case("mariadb"))
    async with case.database.transaction() as transaction:
        await transaction.execute(mariadb.raw("INSERT INTO raw_entries VALUES (2)"))
    barrier = asyncio.Barrier(2)

    async def contend(first: int, second: int) -> str:
        async with case.database.transaction(timeout=3) as transaction:
            try:
                async with transaction.begin_nested():
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
            except mariadb.ExecutionError:
                with assert_raises(mariadb.DatabaseRuntimeError):
                    await transaction.execute(mariadb.raw("SELECT 1"))
                return "discarded"
            return "committed"

    with fail_after(10):
        outcomes = await asyncio.gather(contend(1, 2), contend(2, 1))
    assert_eq(sorted(outcomes), ["committed", "discarded"])


@test(mark="slow")
async def mariadb_late_stream_constraint_remains_terminal() -> None:
    """A constraint packet after stream metadata leaves driver cleanup uncertain."""
    case = await load_fixture(provide_nested_case("mariadb"))

    async with case.database.transaction() as transaction:
        await transaction.execute(mariadb.raw("INSERT INTO nested_entries VALUES (1)"))
        with assert_raises(mariadb.ExecutionError):
            async with transaction.begin_nested():
                async with transaction.fetch_chunks(
                    mariadb.raw(
                        "INSERT INTO nested_entries VALUES (1) RETURNING value"
                    ),
                    size=1,
                ) as stream:
                    await anext(stream)
        with assert_raises(mariadb.DatabaseRuntimeError):
            await transaction.execute(mariadb.raw("SELECT 1"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def lost_savepoint_during_recovery_remains_terminal(
    backend: BackendFamily,
) -> None:
    """Recognition alone is insufficient when rollback cannot find its savepoint."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                )
                # Deliberate transaction-control misuse simulates lost server state.
                await transaction.execute(case.namespace.raw("COMMIT"))
                await transaction.execute(case.namespace.raw("BEGIN"))
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
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
async def recovered_raw_constraint_redacts_driver_values(
    backend: BackendFamily,
) -> None:
    """Recovery must not expose the constraint packet through logs or traceback causes."""
    case = await load_fixture(provide_constraint_case(backend))
    seed = case.namespace.raw(
        "INSERT INTO constrained_entries VALUES (5, 'recovery_value_secret', 1, 1)"
    )
    duplicate = case.namespace.raw(
        "INSERT INTO constrained_entries VALUES (6, 'recovery_value_secret', 1, 1)"
    )
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    logger = logging.getLogger("snekql")
    logger.addHandler(handler)
    try:
        async with case.database.transaction() as transaction:
            await transaction.execute(seed)
            with assert_raises(case.namespace.ExecutionError) as caught:
                async with transaction.begin_nested():
                    await transaction.execute(duplicate)
        rendered = captured.getvalue() + "".join(format_exception(caught.exception))
    finally:
        logger.removeHandler(handler)
    assert_eq("recovery_value_secret" in rendered, False)


@test(mark="medium")
async def sqlite_partial_statement_writes_roll_back_with_savepoint() -> None:
    """SQLite FAIL can retain earlier rows from one statement until scope rollback."""
    case = await load_fixture(provide_nested_case("sqlite"))

    async with case.database.transaction() as transaction:
        await transaction.execute(sqlite.raw("INSERT INTO nested_entries VALUES (1)"))
        with assert_raises(sqlite.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    sqlite.raw("INSERT OR FAIL INTO nested_entries VALUES (2), (1)")
                )
        await transaction.execute(sqlite.raw("INSERT INTO nested_entries VALUES (3)"))

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.raw("SELECT value FROM nested_entries ORDER BY value")
        )
    assert_eq(rows, [{"value": 1}, {"value": 3}])


@test(mark="medium")
async def deferred_constraint_fails_at_outer_commit() -> None:
    """A savepoint cannot recover a constraint the database checks only at commit."""
    case = await load_fixture(provide_nested_case("sqlite"))
    await case.database.migrate(
        {
            "001_entries": "CREATE TABLE nested_entries (value INTEGER PRIMARY KEY)",
            "002_deferred": """CREATE TABLE deferred_children (
            value INTEGER PRIMARY KEY,
            parent INTEGER REFERENCES nested_entries(value) DEFERRABLE INITIALLY DEFERRED
        )""",
        }
    )

    with assert_raises(sqlite.DatabaseRuntimeError):
        async with case.database.transaction() as transaction:
            async with transaction.begin_nested():
                await transaction.execute(
                    sqlite.raw("INSERT INTO deferred_children VALUES (1, 99)")
                )
