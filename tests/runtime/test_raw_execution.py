"""Native raw execution through public Transactions on real databases."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from typing import Any, Literal

from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from snekql.model import BackendFamily
from snekql.runtime import Database
from tests.helpers import provide_mariadb_server


@dataclass(frozen=True)
class RawCase:
    """A backend's public namespace and its independently owned database."""

    database: Database[Any]
    namespace: Any


@fixture
async def provide_raw_case(
    backend: BackendFamily,
    *,
    visibility: Literal["redacted", "values"] = "redacted",
) -> AsyncGenerator[RawCase]:
    if backend == "mariadb":
        server = await load_fixture(provide_mariadb_server())
        async with await mariadb.Database.initialize(
            replace(server.config(), parameter_visibility=visibility)
        ) as database:
            yield RawCase(database, mariadb)
    else:
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:", parameter_visibility=visibility)
        ) as database:
            yield RawCase(database, sqlite)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def named_parameters_keep_sql_markers_as_values(backend: BackendFamily) -> None:
    """Quotes, comments, delimiters, and percent signs never become SQL syntax."""

    case = await load_fixture(provide_raw_case(backend))
    placeholder = ":value" if backend == "sqlite" else "%(value)s"
    statement = case.namespace.raw(
        f"SELECT {placeholder} AS value", params={"value": "' ; -- /* */ 100%"}
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(rows, [{"value": "' ; -- /* */ 100%"}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def duplicate_mapping_names_fail_even_without_rows(
    backend: BackendFamily,
) -> None:
    """Result metadata is checked independently of whether any row exists."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        "SELECT 1 AS private_name, 2 AS private_name WHERE 1=0"
    )

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            await transaction.fetch_all(statement)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def tuple_rows_preserve_positional_order(backend: BackendFamily) -> None:
    """Duplicate aliases do not affect positional native values."""

    case = await load_fixture(provide_raw_case(backend))
    placeholder = "?" if backend == "sqlite" else "%s"
    statement = case.namespace.raw(
        f"SELECT {placeholder} AS duplicate, {placeholder} AS duplicate",
        params=["second", "first"],
        row_mode="tuple",
    )

    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(statement)

    assert_eq(rows, [("second", "first")])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="fetch_one", name="one"),
        Param(value="fetch_one_or_none", name="optional"),
    ],
    mark="slow",
)
async def capped_fetch_rejects_multiple_rows(
    backend: BackendFamily, method: str
) -> None:
    """Raw capped reads use the existing package cardinality errors."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 1 AS value UNION ALL SELECT 2")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.MultipleResultsError):
            await getattr(transaction, method)(statement)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def execute_preserves_native_command_rowcount(backend: BackendFamily) -> None:
    """SQLite's unavailable sentinel is not replaced by a fabricated zero."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("CREATE TEMPORARY TABLE raw_counts (value INTEGER)")

    async with case.database.transaction() as transaction:
        affected = await transaction.execute(statement)

    assert_eq(affected, -1 if backend == "sqlite" else 0)


@test(
    [
        Param(value="SELECT 1 AS value; SELECT 2", name="rowsets"),
        Param(value="DO 1; DO 2", name="commands"),
        Param(value="SELECT 1 AS value; DO 2", name="mixed"),
    ],
    mark="slow",
)
async def additional_results_are_rejected(sql: str) -> None:
    """MariaDB's enabled multi-statements cannot silently return success."""

    case = await load_fixture(provide_raw_case("mariadb"))
    statement = case.namespace.raw(sql)

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            if sql.startswith("DO"):
                await transaction.execute(statement)
            else:
                await transaction.fetch_one(statement)


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def stream_yields_bounded_chunks(backend: BackendFamily) -> None:
    """Raw streaming uses the existing context-manager and size contract."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw(
        "SELECT 1 AS value UNION ALL SELECT 2 UNION ALL SELECT 3"
    )

    async with (
        case.database.transaction() as transaction,
        transaction.fetch_chunks(statement, size=2) as stream,
    ):
        chunks = [chunk async for chunk in stream]

    assert_eq(chunks, [[{"value": 1}, {"value": 2}], [{"value": 3}]])


@test(
    [Param(value="early", name="early"), Param(value="exhausted", name="exhausted")],
    mark="slow",
)
async def stream_completion_rejects_additional_results(exit_mode: str) -> None:
    """Draining the first streamed result detects later command responses."""

    case = await load_fixture(provide_raw_case("mariadb"))
    statement = case.namespace.raw("SELECT 1 AS value UNION ALL SELECT 2; DO 1")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            async with transaction.fetch_chunks(statement, size=1) as stream:
                async for _ in stream:
                    if exit_mode == "early":
                        break


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def stream_rejects_duplicate_metadata_before_entry(
    backend: BackendFamily,
) -> None:
    """A malformed mapping never exposes a chunk, even when there are no rows."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 1 AS secret, 2 AS secret WHERE 1=0")
    entered = False

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            async with transaction.fetch_chunks(statement, size=1):
                entered = True
        observed = await transaction.fetch_one(case.namespace.raw("SELECT 3 AS value"))

    assert_eq((entered, observed), (False, {"value": 3}))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="omitted", name="omitted"),
        Param(value="none", name="none"),
        Param(value="tuple", name="tuple"),
        Param(value="mapping", name="mapping"),
    ],
    mark="slow",
)
async def native_percent_formatting_preserves_parameter_presence(
    backend: BackendFamily, container: str
) -> None:
    """Only supplied MariaDB parameter containers invoke native percent formatting."""

    case = await load_fixture(provide_raw_case(backend))
    sql = "SELECT '100%%' AS value"
    if container == "omitted":
        statement = case.namespace.raw(sql)
    else:
        params = {"none": None, "tuple": (), "mapping": {}}[container]
        statement = case.namespace.raw(sql, params=params)

    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    expected = (
        "100%"
        if backend == "mariadb" and container in ("tuple", "mapping")
        else "100%%"
    )
    assert_eq(row, {"value": expected})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [Param(value="mapping", name="mapping"), Param(value="sequence", name="sequence")],
    mark="slow",
)
async def parameter_membership_is_snapshotted(
    backend: BackendFamily, container: str
) -> None:
    """Clearing the original container cannot change a later execution."""

    case = await load_fixture(provide_raw_case(backend))
    if container == "mapping":
        params: dict[str, object] | list[object] = {"value": "captured"}
        placeholder = ":value" if backend == "sqlite" else "%(value)s"
    else:
        params = ["captured"]
        placeholder = "?" if backend == "sqlite" else "%s"
    statement = case.namespace.raw(f"SELECT {placeholder} AS value", params=params)
    params.clear()

    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, {"value": "captured"})


@test(mark="medium")
async def driver_ready_mutable_values_are_not_deep_copied() -> None:
    """SQLite accepts a bytearray whose membership snapshot remains shallow."""

    case = await load_fixture(provide_raw_case("sqlite"))
    value = bytearray(b"before")
    statement = sqlite.raw("SELECT ? AS value", params=[value])
    value[:] = b"after"

    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, {"value": b"after"})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value="SELECT 1 AS value", name="nonempty"),
        Param(value="SELECT 1 AS value WHERE 1=0", name="empty"),
    ],
    mark="slow",
)
async def execute_rejects_result_columns(backend: BackendFamily, sql: str) -> None:
    """A rowset is not an affected-rowcount response, even when empty."""

    case = await load_fixture(provide_raw_case(backend))

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            await transaction.execute(case.namespace.raw(sql))
        row = await transaction.fetch_one(case.namespace.raw("SELECT 2 AS value"))

    assert_eq(row, {"value": 2})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in (
            "execute",
            "fetch_all",
            "fetch_one",
            "fetch_one_or_none",
            "fetch_chunks",
        )
    ],
    mark="slow",
)
async def wrong_backend_is_rejected_before_execution(
    backend: BackendFamily, method: str
) -> None:
    """All consumption methods preserve namespace identity without poisoning the transaction."""

    case = await load_fixture(provide_raw_case(backend))
    foreign = mariadb if backend == "sqlite" else sqlite
    statement = foreign.raw("SELECT 1")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.QueryConstructionError):
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=1):
                    pass
            else:
                await getattr(transaction, method)(statement)
        row = await transaction.fetch_one(case.namespace.raw("SELECT 2 AS value"))

    assert_eq(row, {"value": 2})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in (
            "execute",
            "fetch_all",
            "fetch_one",
            "fetch_one_or_none",
            "fetch_chunks",
        )
    ],
    mark="slow",
)
async def transaction_validation_cannot_disable_statement_policy(
    backend: BackendFamily, method: str
) -> None:
    """False is rejected even for an unvalidated raw statement."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 1")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.QueryConstructionError):
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=1, validate=False):
                    pass
            else:
                await getattr(transaction, method)(statement, validate=False)
        row = await transaction.fetch_one(case.namespace.raw("SELECT 2 AS value"))

    assert_eq(row, {"value": 2})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def statements_can_be_reused_across_transactions(backend: BackendFamily) -> None:
    """No cursor position or result metadata persists on a raw statement."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 1 AS value")

    async with case.database.transaction() as transaction:
        first = await transaction.fetch_one(statement)
    async with case.database.transaction() as transaction:
        second = await transaction.fetch_all(statement)

    assert_eq((first, second), ({"value": 1}, [{"value": 1}]))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def mapping_names_preserve_exact_case(backend: BackendFamily) -> None:
    """Driver aliases are dictionary keys, not normalized model field names."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 2 AS Value, 1 AS value")

    async with case.database.transaction() as transaction:
        row = await transaction.fetch_one(statement)

    assert_eq(row, {"value": 1, "Value": 2})


@fixture
async def provide_raw_table(backend: BackendFamily) -> AsyncGenerator[RawCase]:
    case = await load_fixture(provide_raw_case(backend))
    await case.database.migrate(
        {"001_table": "CREATE TABLE raw_entries (value INTEGER PRIMARY KEY)"}
    )
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw("INSERT INTO raw_entries VALUES (1)")
        )
    yield case


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def uncaught_returning_cardinality_failure_rolls_back(
    backend: BackendFamily,
) -> None:
    """Transactional writes roll back when their result error exits Transaction."""

    case = await load_fixture(provide_raw_table(backend))
    statement = case.namespace.raw(
        "INSERT INTO raw_entries VALUES (2), (3) RETURNING value"
    )

    with assert_raises(case.namespace.MultipleResultsError):
        async with case.database.transaction() as transaction:
            await transaction.fetch_one(statement)
    async with case.database.transaction() as transaction:
        rows = await transaction.fetch_all(
            case.namespace.raw("SELECT value FROM raw_entries")
        )

    assert_eq(rows, [{"value": 1}])


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def caught_returning_shape_failure_can_commit(backend: BackendFamily) -> None:
    """Rejecting returned rows does not undo an executed write when caught."""

    case = await load_fixture(provide_raw_table(backend))
    statement = case.namespace.raw("INSERT INTO raw_entries VALUES (2) RETURNING value")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            await transaction.execute(statement)
        pending = await transaction.fetch_one(
            case.namespace.raw("SELECT value FROM raw_entries WHERE value=2")
        )
    async with case.database.transaction() as transaction:
        committed = await transaction.fetch_one(
            case.namespace.raw("SELECT value FROM raw_entries WHERE value=2")
        )

    assert_eq((pending, committed), ({"value": 2}, {"value": 2}))


@test(
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "early_stream", "exhausted_stream")
    ],
    mark="slow",
)
async def stored_procedure_trailing_response_is_not_exempt(method: str) -> None:
    """A routine's trailing command response is still an additional result."""

    case = await load_fixture(provide_raw_case("mariadb"))
    async with case.database.transaction() as transaction:
        await transaction.execute(
            case.namespace.raw(
                "CREATE PROCEDURE raw_trailing() SELECT 1 AS value UNION ALL SELECT 2"
            )
        )
    statement = case.namespace.raw("CALL raw_trailing()")

    try:
        async with case.database.transaction() as transaction:
            with assert_raises(case.namespace.RawResultShapeError):
                if method in ("early_stream", "exhausted_stream"):
                    async with transaction.fetch_chunks(statement, size=1) as stream:
                        async for _ in stream:
                            if method == "early_stream":
                                break
                else:
                    await getattr(transaction, method)(statement)
    finally:
        async with case.database.transaction() as transaction:
            await transaction.execute(case.namespace.raw("DROP PROCEDURE raw_trailing"))


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    [
        Param(value=method, name=method)
        for method in ("fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks")
    ],
    mark="slow",
)
async def fetching_a_command_rejects_shape_after_execution(
    backend: BackendFamily, method: str
) -> None:
    """Missing result columns are not an empty result and do not prevent effects."""

    case = await load_fixture(provide_raw_table(backend))
    statement = case.namespace.raw("INSERT INTO raw_entries VALUES (2)")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.RawResultShapeError):
            if method == "fetch_chunks":
                async with transaction.fetch_chunks(statement, size=1):
                    pass
            else:
                await getattr(transaction, method)(statement)
        row = await transaction.fetch_one(
            case.namespace.raw("SELECT value FROM raw_entries WHERE value=2")
        )

    assert_eq(row, {"value": 2})


@test(
    [
        Param[BackendFamily](value="sqlite", name="sqlite"),
        Param[BackendFamily](value="mariadb", name="mariadb"),
    ],
    mark="slow",
)
async def empty_rows_keep_consumption_cardinality(backend: BackendFamily) -> None:
    """A well-shaped empty result differs from a command without result columns."""

    case = await load_fixture(provide_raw_case(backend))
    statement = case.namespace.raw("SELECT 1 AS value WHERE 1=0")

    async with case.database.transaction() as transaction:
        with assert_raises(case.namespace.NoResultError):
            await transaction.fetch_one(statement)
        optional = await transaction.fetch_one_or_none(statement)
        all_rows = await transaction.fetch_all(statement)
        async with transaction.fetch_chunks(statement, size=1) as stream:
            chunks = [chunk async for chunk in stream]

    assert_eq((optional, all_rows, chunks), (None, [], []))
