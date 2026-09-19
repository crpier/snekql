"""Explicit transaction policies are enforced without leaking pooled settings."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal, assert_type
from unittest.mock import patch

from aiosqlite import Connection, Cursor, OperationalError
from anyio import CancelScope, lowlevel, move_on_after, sleep_forever
from snektest import Param, assert_eq, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import IsolationLevel
from tests.helpers import provide_mariadb_server
from tests.runtime.test_nested_transactions import provide_nested_case
from tests.runtime.test_raw_lifecycle import provide_contended_case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def read_only_transaction_rejects_writes(backend: BackendFamily) -> None:
    """The database rejects raw writes as well as builder writes."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction(read_only=True) as transaction:
        rows = await transaction.fetch_all(case.namespace.raw("SELECT 1 AS value"))
        assert_eq(rows, [{"value": 1}])
        with assert_raises(case.namespace.ExecutionError):
            await transaction.execute(
                case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
            )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def read_only_does_not_leak_to_next_transaction(backend: BackendFamily) -> None:
    """The sole pooled connection returns to its previous access mode after success."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction(read_only=True) as transaction:
        await transaction.fetch_all(case.namespace.raw("SELECT 1"))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM nested_entries")
        )
    assert_eq(rows, [{"value": 1}])


@test(mark="slow")
async def read_committed_observes_later_commits() -> None:
    """Each consistent read sees commits completed before that statement."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction(isolation="read_committed") as reader:
        await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
        async with case.database.transaction() as writer:
            await writer.execute(
                mariadb.raw("UPDATE raw_entries SET value=2 WHERE value=1")
            )
        rows = await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
    assert_eq(rows, [{"value": 2}])


@test(
    [
        Param[IsolationLevel](value=level, name=level)
        for level in ("read_uncommitted", "read_committed", "repeatable_read")
    ],
    mark="medium",
)
async def sqlite_rejects_unsupported_isolation_before_acquisition(
    level: IsolationLevel,
) -> None:
    """An explicit unsupported level fails even while the only connection is busy."""
    case = await load_fixture(provide_nested_case("sqlite"))

    async with case.database.transaction():
        with assert_raises(sqlite.DatabaseRuntimeError):
            case.database.transaction(isolation=level)


@test(mark="medium")
async def sqlite_rejects_read_only_write_intent() -> None:
    """A read-only request must not acquire the database's writer reservation."""
    case = await load_fixture(provide_nested_case("sqlite"))

    with assert_raises(sqlite.DatabaseRuntimeError):
        case.database.transaction(read_only=True, mode="immediate")


@test(mark="medium")
async def sqlite_serializable_restores_previous_isolation_setting() -> None:
    """An explicit level overrides and then restores the actual connection setting."""
    case = await load_fixture(provide_nested_case("sqlite"))
    async with case.database.transaction() as transaction:
        await transaction.execute(sqlite.raw("PRAGMA read_uncommitted=1"))

    async with case.database.transaction(isolation="serializable") as transaction:
        active = await transaction.fetch_one(sqlite.raw("PRAGMA read_uncommitted"))
    async with case.database.transaction() as transaction:
        restored = await transaction.fetch_one(sqlite.raw("PRAGMA read_uncommitted"))
    assert_eq(active, {"read_uncommitted": 0})
    assert_eq(restored, {"read_uncommitted": 1})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def read_only_rollback_restores_access_mode(backend: BackendFamily) -> None:
    """Application failure restores the pooled connection after rollback."""
    case = await load_fixture(provide_nested_case(backend))
    failure = case.namespace.ModelValidationError("application failure")

    with assert_raises(case.namespace.ModelValidationError):
        async with case.database.transaction(read_only=True):
            raise failure
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def explicit_read_write_preserves_read_only_default(
    backend: BackendFamily,
) -> None:
    """False is an explicit override, not a request to inherit the connection default."""
    case = await load_fixture(provide_nested_case(backend))
    setting = (
        "PRAGMA query_only=1" if backend == "sqlite" else "SET SESSION tx_read_only=1"
    )
    probe = (
        "SELECT query_only AS read_only FROM pragma_query_only"
        if backend == "sqlite"
        else "SELECT @@tx_read_only AS read_only"
    )
    async with case.database.transaction() as transaction:
        await transaction.execute(case.namespace.raw(setting))

    async with case.database.transaction(read_only=False) as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )
    async with case.database.transaction() as transaction:
        restored = await transaction.fetch_one(case.namespace.raw(probe))
    assert_eq(restored, {"read_only": 1})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def cancellation_restores_transaction_policy(backend: BackendFamily) -> None:
    """Cancellation between driver calls rolls back before returning the connection."""
    case = await load_fixture(provide_nested_case(backend))

    with CancelScope() as cancellation:
        async with case.database.transaction(read_only=True):
            cancellation.cancel()
            await lowlevel.checkpoint()
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
        )


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def savepoint_inherits_read_only_policy(backend: BackendFamily) -> None:
    """A nested context cannot turn its outer read-only transaction into a writer."""
    case = await load_fixture(provide_nested_case(backend))

    async with case.database.transaction(read_only=True) as transaction:
        with assert_raises(case.namespace.ExecutionError):
            async with transaction.begin_nested():
                await transaction.execute(
                    case.namespace.raw("INSERT INTO nested_entries VALUES (1)")
                )


@test(
    [
        Param[IsolationLevel](value="read_committed", name="read_committed"),
        Param[IsolationLevel](value="repeatable_read", name="repeatable_read"),
    ],
    [Param(value=True, name="read_only"), Param(value=False, name="read_write")],
    mark="slow",
)
async def isolation_combines_with_access_mode(
    level: IsolationLevel,
    read_only: bool,  # noqa: FBT001 - parameterized test input
) -> None:
    """Setting access mode must not erase the requested visibility policy."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction(
        isolation=level, read_only=read_only
    ) as reader:
        await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
        async with case.database.transaction() as writer:
            await writer.execute(
                mariadb.raw("UPDATE raw_entries SET value=2 WHERE value=1")
            )
        rows = await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
    assert_eq(rows, [{"value": 2 if level == "read_committed" else 1}])


@test(mark="slow")
async def read_uncommitted_observes_uncommitted_writes() -> None:
    """The weakest InnoDB isolation level is explicit rather than a silent default."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction() as writer:
        await writer.execute(
            mariadb.raw("UPDATE raw_entries SET value=2 WHERE value=1")
        )
        async with case.database.transaction(isolation="read_uncommitted") as reader:
            rows = await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
    assert_eq(rows, [{"value": 2}])


@test(mark="slow")
async def serializable_reads_block_conflicting_writes() -> None:
    """InnoDB's serializable reads hold locks until the transaction ends."""
    case = await load_fixture(provide_contended_case("mariadb"))

    async with case.database.transaction(isolation="serializable") as reader:
        await reader.fetch_all(mariadb.raw("SELECT value FROM raw_entries"))
        with assert_raises(mariadb.DatabaseOperationTimeoutError):
            async with case.database.transaction(timeout=0.03) as writer:
                await writer.execute(
                    mariadb.raw("UPDATE raw_entries SET value=2 WHERE value=1")
                )


@test(mark="medium")
async def restoration_failure_discards_read_only_connection() -> None:
    """A failed reset must not hand the next borrower a read-only connection."""
    case = await load_fixture(provide_nested_case("sqlite"))
    native_execute = Connection.execute

    async def fail_pragma(
        connection: Connection, sql: str, parameters: Iterable[Any] | None = None
    ) -> Cursor:
        if sql.startswith("PRAGMA"):
            message = "driver policy restoration failed"
            raise OperationalError(message)
        return await native_execute(connection, sql, parameters)

    transaction = case.database.transaction(read_only=True)
    await transaction.__aenter__()
    with (
        patch.object(Connection, "execute", fail_pragma),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await transaction.__aexit__(None, None, None)

    async with case.database.transaction() as next_transaction:
        access = await next_transaction.fetch_one(
            sqlite.raw("SELECT query_only AS read_only FROM pragma_query_only")
        )
    assert_eq(access, {"read_only": 0})


@test(mark="medium")
async def restoration_failure_can_follow_successful_commit() -> None:
    """A cleanup error does not imply that already-committed writes were rolled back."""
    case = await load_fixture(provide_contended_case("sqlite"))
    native_execute = Connection.execute

    async def fail_pragma(
        connection: Connection, sql: str, parameters: Iterable[Any] | None = None
    ) -> Cursor:
        if sql.startswith("PRAGMA"):
            message = "driver policy restoration failed"
            raise OperationalError(message)
        return await native_execute(connection, sql, parameters)

    transaction = case.database.transaction(read_only=False)
    await transaction.__aenter__()
    await transaction.execute(
        sqlite.raw("UPDATE raw_entries SET value=2 WHERE value=1")
    )
    with (
        patch.object(Connection, "execute", fail_pragma),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        await transaction.__aexit__(None, None, None)

    async with case.database.transaction() as next_transaction:
        rows = await next_transaction.fetch_all(
            sqlite.raw("SELECT value FROM raw_entries")
        )
    assert_eq(rows, [{"value": 2}])


@test(
    [
        Param[Literal["timeout", "cancel"]](value="timeout", name="timeout"),
        Param[Literal["timeout", "cancel"]](value="cancel", name="cancel"),
    ],
    mark="medium",
)
async def interrupted_policy_begin_discards_modified_connection(
    interruption: Literal["timeout", "cancel"],
) -> None:
    """Interruption after PRAGMA setup but before BEGIN cannot leak that setup."""
    case = await load_fixture(provide_nested_case("sqlite"))
    native_execute = Connection.execute

    async def block_begin(
        connection: Connection, sql: str, parameters: Iterable[Any] | None = None
    ) -> Cursor:
        if sql == "BEGIN":
            await sleep_forever()
        return await native_execute(connection, sql, parameters)

    with patch.object(Connection, "execute", block_begin):
        if interruption == "timeout":
            with assert_raises(sqlite.DatabaseOperationTimeoutError):
                async with case.database.transaction(read_only=True, timeout=0.03):
                    pass
        else:
            with move_on_after(0.03) as cancellation:
                async with case.database.transaction(read_only=True):
                    pass
            assert_eq(cancellation.cancel_called, True)

    async with case.database.transaction() as next_transaction:
        access = await next_transaction.fetch_one(
            sqlite.raw("SELECT query_only AS read_only FROM pragma_query_only")
        )
    assert_eq(access, {"read_only": 0})


@test(mark="medium")
async def transaction_policy_arguments_are_strict() -> None:
    """Dynamic arguments cannot coerce booleans or introduce unrecognized SQL levels."""
    case = await load_fixture(provide_nested_case("sqlite"))

    with assert_raises(sqlite.DatabaseRuntimeError):
        case.database.transaction(read_only=1)  # ty: ignore[invalid-argument-type]
    with assert_raises(sqlite.DatabaseRuntimeError):
        case.database.transaction(isolation="serializable; COMMIT")  # ty: ignore[invalid-argument-type]


@test(
    [
        Param[IsolationLevel](value=level, name=level)
        for level in (
            "read_uncommitted",
            "read_committed",
            "repeatable_read",
            "serializable",
        )
    ],
    mark="slow",
)
async def mariadb_isolation_override_does_not_leak(level: IsolationLevel) -> None:
    """A subsequent lease of the same physical connection uses its session default."""
    server = await load_fixture(provide_mariadb_server())

    async with (
        await mariadb.Database.initialize(server.config(pool_size=1)) as database,
        await mariadb.Database.initialize(server.config(pool_size=1)) as concurrent,
    ):
        await database.migrate(
            {
                "001_entries": "CREATE TABLE isolation_entries (value INTEGER PRIMARY KEY)"
            }
        )
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.raw("INSERT INTO isolation_entries VALUES (1)")
            )
            await transaction.execute(
                mariadb.raw("SET SESSION tx_isolation='REPEATABLE-READ'")
            )
        async with database.transaction(isolation=level, read_only=True) as transaction:
            await transaction.fetch_one(mariadb.raw("SELECT 1"))

        async with database.transaction() as reader:
            await reader.fetch_all(mariadb.raw("SELECT value FROM isolation_entries"))
            async with concurrent.transaction() as writer:
                await writer.execute(
                    mariadb.raw("UPDATE isolation_entries SET value=2 WHERE value=1")
                )
            rows = await reader.fetch_all(
                mariadb.raw("SELECT value FROM isolation_entries")
            )
        assert_eq(rows, [{"value": 1}])


if TYPE_CHECKING:

    def sqlite_policy_helper(database: sqlite.Database) -> sqlite.Transaction:
        """Policy options retain the transaction's backend witness."""
        level: sqlite.IsolationLevel = "serializable"
        transaction = database.transaction(isolation=level, read_only=True)
        assert_type(transaction, sqlite.Transaction)
        return transaction

    def mariadb_policy_helper(database: mariadb.Database) -> mariadb.Transaction:
        """Both backend namespaces expose the same constrained isolation vocabulary."""
        level: mariadb.IsolationLevel = "read_committed"
        transaction = database.transaction(isolation=level, read_only=False)
        assert_type(transaction, mariadb.Transaction)
        return transaction
