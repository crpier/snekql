"""Backend-aware plan inspection through public Transactions."""

import json
from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError
from traceback import format_exception
from typing import ClassVar, Literal
from unittest.mock import AsyncMock, patch

from aiomysql import Cursor as MariaCursor
from aiosqlite import Cursor as SQLiteCursor
from anyio import fail_after
from snektest import (
    Param,
    assert_eq,
    assert_raises,
    assert_true,
    fixture,
    load_fixture,
    test,
)

from snekql import mariadb, sqlite
from tests.helpers import capture_snekql_logs, provide_mariadb_server


class Account[S = sqlite.Pending](sqlite.Model[S]):
    """Rows used to distinguish query plans from query results."""

    __row_type__: ClassVar[sqlite.ReadType[Account[sqlite.Row]]]

    account_id: Account.Col[int] = sqlite.Integer(primary_key=True)
    email: Account.Col[str] = sqlite.Text()


@fixture
async def provide_sqlite_accounts() -> AsyncGenerator[sqlite.Database]:
    """Create a populated table before plan inspection."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        async with database.transaction() as transaction:
            await transaction.execute(sqlite.raw(sqlite.scaffold([Account])))
            await transaction.execute(
                sqlite.insert(Account(account_id=7, email="secret"))
            )
        yield database


@test(mark="medium")
async def sqlite_explain_returns_native_plan_rows() -> None:
    """EXPLAIN returns metadata and plan cells, not selected model values."""
    database = await load_fixture(provide_sqlite_accounts())

    async with database.transaction() as transaction:
        plan = await transaction.explain(
            sqlite.select(Account.email).where(Account.account_id.eq(7))
        )

    assert_eq(plan.backend, "sqlite")
    assert_eq(plan.columns, ("id", "parent", "notused", "detail"))
    assert_true(isinstance(plan.rows, tuple))
    assert_true(any("SEARCH account" in str(row[3]) for row in plan.rows))


class MariaAccount[S = mariadb.Pending](mariadb.Model[S]):
    """MariaDB rows used for plan inspection and explicit write execution."""

    __row_type__: ClassVar[mariadb.ReadType[MariaAccount[mariadb.Row]]]

    account_id: MariaAccount.Col[int] = mariadb.Integer(primary_key=True)
    email: MariaAccount.Col[str] = mariadb.Text()


@fixture
async def provide_mariadb_accounts() -> AsyncGenerator[mariadb.Database]:
    """Create a populated table on the temporary MariaDB server."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(
        server.config(pool_size=2)
    ) as database:
        async with database.transaction() as transaction:
            await transaction.execute(mariadb.raw(mariadb.scaffold([MariaAccount])))
            await transaction.execute(
                mariadb.insert(MariaAccount(account_id=7, email="secret"))
            )
        yield database


@test(mark="slow")
async def mariadb_explain_returns_native_plan_rows() -> None:
    """MariaDB column metadata describes the optimizer output, not selected rows."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        plan = await transaction.explain(
            mariadb.select(MariaAccount.email).where(MariaAccount.account_id.eq(7))
        )

    assert_eq(plan.backend, "mariadb")
    assert_true("select_type" in plan.columns)
    assert_true("key" in plan.columns)
    assert_eq(plan.rows[0][plan.columns.index("key")], "PRIMARY")


@test(mark="slow")
async def analyze_select_returns_observed_statistics() -> None:
    """The explicit executing method returns native actual-row statistics."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        plan = await transaction.explain_analyze(mariadb.select(MariaAccount))

    assert_true("r_rows" in plan.columns)
    assert_true("r_filtered" in plan.columns)
    assert_true(bool(plan.rows))


@test([Param("explain", name="explain"), Param("analyze", name="analyze")], mark="slow")
async def mariadb_rejects_explaining_insert(mode: str) -> None:
    """Unsupported INSERT plans fail at compilation, not in the driver."""
    database = await load_fixture(provide_mariadb_accounts())
    query = mariadb.insert(MariaAccount(account_id=8, email="unwritten"))

    async with database.transaction() as transaction:
        with assert_raises(mariadb.QueryCompilationError):
            if mode == "analyze":
                await transaction.explain_analyze(query)
            else:
                await transaction.explain(query)


@test([Param("explain", name="explain"), Param("analyze", name="analyze")], mark="slow")
async def mariadb_rejects_explaining_returning_writes(mode: str) -> None:
    """Plan inspection never mistakes RETURNING values for optimizer rows."""
    database = await load_fixture(provide_mariadb_accounts())
    query = mariadb.delete(MariaAccount).all().returning()

    async with database.transaction() as transaction:
        with assert_raises(mariadb.QueryCompilationError):
            if mode == "analyze":
                await transaction.explain_analyze(query)
            else:
                await transaction.explain(query)


@test(mark="fast")
def explain_result_is_exported_by_both_namespaces() -> None:
    """Applications can annotate native plan results without private imports."""
    assert_eq(sqlite.ExplainResult, mariadb.ExplainResult)


@test(mark="fast")
def explain_result_text_omits_optimizer_cells() -> None:
    """Optimizer text may contain bound values, so formatting shows counts only."""
    plan = sqlite.ExplainResult(
        backend="sqlite", columns=("private_column",), rows=(("private_value",),)
    )

    assert_eq(repr(plan), "ExplainResult(backend='sqlite', columns=1, rows=1)")
    assert_eq(str(plan), repr(plan))
    assert_eq(plan.rows, (("private_value",),))


@test(
    [
        Param("insert", name="insert"),
        Param("update", name="update"),
        Param("delete", name="delete"),
    ],
    mark="medium",
)
async def sqlite_explain_does_not_apply_writes(kind: str) -> None:
    """Planning write statements leaves persisted rows unchanged."""
    database = await load_fixture(provide_sqlite_accounts())
    queries = {
        "insert": sqlite.insert(Account(account_id=8, email="new")),
        "update": sqlite.update(Account).set(Account.email.to("new")).all(),
        "delete": sqlite.delete(Account).all(),
    }

    async with database.transaction() as transaction:
        await transaction.explain(queries[kind])
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(Account.account_id, Account.email)
        )

    assert_eq(rows, [(7, "secret")])


@test(
    [Param("update", name="update"), Param("delete", name="delete")],
    [
        Param[Literal["native", "json"]]("native", name="native"),
        Param[Literal["native", "json"]]("json", name="json"),
    ],
    mark="slow",
)
async def mariadb_explain_does_not_apply_writes(
    kind: str, plan_format: Literal["native", "json"]
) -> None:
    """Plain EXPLAIN never opts a write into executing ANALYZE."""
    database = await load_fixture(provide_mariadb_accounts())
    queries = {
        "update": mariadb.update(MariaAccount).set(MariaAccount.email.to("new")).all(),
        "delete": mariadb.delete(MariaAccount).all(),
    }

    async with database.transaction() as transaction:
        await transaction.explain(queries[kind], format=plan_format)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))

    assert_eq(rows, ["secret"])


@test(
    [Param("update", name="update"), Param("delete", name="delete")],
    [
        Param[Literal["native", "json"]]("native", name="native"),
        Param[Literal["native", "json"]]("json", name="json"),
    ],
    mark="slow",
)
async def analyze_write_commits_on_normal_transaction_exit(
    kind: str, plan_format: Literal["native", "json"]
) -> None:
    """Explicit ANALYZE actually applies writes using normal transaction rules."""
    database = await load_fixture(provide_mariadb_accounts())
    queries = {
        "update": mariadb.update(MariaAccount)
        .set(MariaAccount.email.to("changed"))
        .all(),
        "delete": mariadb.delete(MariaAccount).all(),
    }

    async with database.transaction() as transaction:
        await transaction.explain_analyze(queries[kind], format=plan_format)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))

    assert_eq(rows, ["changed"] if kind == "update" else [])


@test(mark="slow")
async def analyze_write_respects_transaction_rollback() -> None:
    """A caller's failed transaction rolls back the analyzed write."""
    database = await load_fixture(provide_mariadb_accounts())

    with assert_raises(mariadb.QueryConstructionError):
        async with database.transaction() as transaction:
            await transaction.explain_analyze(mariadb.delete(MariaAccount).all())
            msg = "abort transaction"
            raise mariadb.QueryConstructionError(msg)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))

    assert_eq(rows, ["secret"])


@test(mark="medium")
async def sqlite_analyze_is_rejected_before_query_io() -> None:
    """SQLite ANALYZE is not an execution-statistics substitute."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain_analyze(sqlite.select(Account))


@test(mark="medium")
async def explain_rejects_backend_mismatch_before_query_io() -> None:
    """A wrong-family query fails without looking for its table on SQLite."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError) as raised:
            await transaction.explain(mariadb.select(MariaAccount))  # ty: ignore[invalid-argument-type]

    assert_eq(type(raised.exception), sqlite.DatabaseRuntimeError)
    assert_true("backend mismatch" in str(raised.exception))


@test(mark="medium")
async def explain_rejects_incomplete_write_before_io() -> None:
    """EXPLAIN preserves the write-side explicit row-scope requirement."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain(sqlite.delete(Account))  # ty: ignore[invalid-argument-type]


@test(mark="medium")
async def explain_rejects_empty_bulk_insert() -> None:
    """A no-op batch retains its model but has no SQL to explain."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain(sqlite.insert_many(Account, []))


@test(mark="medium")
async def explain_requires_an_active_transaction() -> None:
    """Plan inspection follows the same lifecycle as query execution."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        transaction = database.transaction()
        with assert_raises(sqlite.TransactionNotStartedError):
            await transaction.explain(sqlite.select(Account))


@test(
    [
        Param[Literal["redacted", "values"]]("redacted", name="redacted"),
        Param[Literal["redacted", "values"]]("values", name="values"),
    ],
    mark="medium",
)
async def explain_errors_omit_sql_and_bindings(
    visibility: Literal["redacted", "values"],
) -> None:
    """Plan inspection uses safe diagnostics even with query-value logging enabled."""
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:", parameter_visibility=visibility)
    ) as database:
        query = sqlite.select(Account).where(Account.email.eq("bound_secret"))
        with capture_snekql_logs() as logs:
            async with database.transaction() as transaction:
                with assert_raises(sqlite.ExecutionError) as raised:
                    await transaction.explain(query)
            rendered = "".join(record.getMessage() for record in logs.records)
            rendered += "".join(format_exception(raised.exception))

    assert_true("raw driver operation failed" in rendered)
    assert_eq("account" in rendered, False)
    assert_eq("bound_secret" in rendered, False)
    assert_eq(raised.exception.sql, "")
    assert_eq(raised.exception.params, ())


@test(mark="medium")
async def explain_success_logs_omit_bindings() -> None:
    """Successful plan diagnostics do not print SQL or bound values."""
    database = await load_fixture(provide_sqlite_accounts())

    with capture_snekql_logs() as logs:
        async with database.transaction() as transaction:
            plan = await transaction.explain(
                sqlite.select(Account).where(Account.email.eq("bound_secret"))
            )
        rendered = "".join(record.getMessage() for record in logs.records) + repr(plan)

    assert_true("explain executed" in rendered)
    assert_eq("bound_secret" in rendered, False)
    assert_eq("account" in rendered, False)


@test(
    [
        Param("backend", name="backend"),
        Param("columns", name="columns"),
        Param("rows", name="rows"),
    ],
    mark="fast",
)
def explain_result_fields_are_frozen(field_name: str) -> None:
    """Result fields cannot change after return from a Transaction."""
    plan = sqlite.ExplainResult(
        backend="sqlite", columns=("detail",), rows=(("scan",),)
    )

    with assert_raises(FrozenInstanceError):
        setattr(plan, field_name, "replacement")


@test(mark="slow")
async def analyzed_write_timeout_discards_the_blocked_connection() -> None:
    """Executing ANALYZE uses the deadline and fail-closed connection policy."""
    database = await load_fixture(provide_mariadb_accounts())

    with fail_after(5):
        async with database.transaction() as owner:
            await owner.execute(
                mariadb.update(MariaAccount).set(MariaAccount.email.to("locked")).all()
            )
            async with database.transaction(timeout=0.03) as waiter:
                with assert_raises(mariadb.DatabaseOperationTimeoutError):
                    await waiter.explain_analyze(
                        mariadb.update(MariaAccount)
                        .set(MariaAccount.email.to("blocked"))
                        .all()
                    )
                with assert_raises(mariadb.DatabaseRuntimeError):
                    await waiter.explain(mariadb.select(MariaAccount))
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))

    assert_eq(rows, ["locked"])


@test([Param("compiled", name="compiled"), Param("raw", name="raw")], mark="medium")
async def explain_accepts_only_built_queries(kind: str) -> None:
    """Arbitrary SQL and inspection snapshots cannot bypass statement policy."""
    queries = {
        "compiled": sqlite.select(Account).compile(),
        "raw": sqlite.raw("DELETE FROM account"),
    }
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain(queries[kind])  # ty: ignore[invalid-argument-type]


@test(mark="slow")
async def analyzed_write_keeps_values_bound() -> None:
    """SQL punctuation in the assignment remains data with predicate bindings."""
    database = await load_fixture(provide_mariadb_accounts())
    email = "quote' ? %s ; --"
    query = (
        mariadb.update(MariaAccount)
        .set(MariaAccount.email.to(email))
        .where(MariaAccount.account_id.eq(7))
    )

    async with database.transaction() as transaction:
        await transaction.explain_analyze(query)
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))

    assert_eq(rows, [email])


@test(mark="medium")
async def sqlite_plan_is_typed_and_traversable_without_losing_native_steps() -> None:
    """A consumer can walk a scalar subquery and inspect its nested table access."""
    database = await load_fixture(provide_sqlite_accounts())
    query = sqlite.select(
        Account.email, sqlite.scalar(sqlite.select(Account.account_id.max()))
    )

    async with database.transaction() as transaction:
        result = await transaction.explain(query)

    plan = result.plan
    assert isinstance(plan, sqlite.SQLiteQueryPlan)
    steps = tuple(plan.walk())
    assert_true(len(steps) >= 3)
    subquery = next(step for step in steps if "SCALAR SUBQUERY" in step.detail)
    assert_true(any("SEARCH account" in child.detail for child in subquery.children))
    assert_true(all(child.parent == subquery.id for child in subquery.children))
    assert_eq(
        {(step.id, step.parent, step.auxiliary, step.detail) for step in steps},
        set(result.rows),
    )
    assert_eq(result.analyzed, False)
    assert_eq(result.format, "native")


@test(mark="slow")
async def mariadb_json_plan_exposes_access_evidence_and_preserves_native_json() -> None:
    """An analyzer can inspect table access without decoding native JSON itself."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        result = await transaction.explain(
            mariadb.select(MariaAccount).where(MariaAccount.email.eq("secret")),
            format="json",
        )

    plan = result.plan
    assert isinstance(plan, mariadb.MariaDBQueryPlan)
    table = next(node for node in plan.walk() if node.operation == "table")
    assert_eq(table.table_name, "maria_account")
    assert_eq(table.access_type, "ALL")
    assert_eq(table.key, None)
    assert_eq(table.estimated_rows, 1.0)
    assert_eq(table.estimated_filtered_percent, 100.0)
    assert_eq(table.actual_rows, None)
    assert_eq(table.actual_loops, None)
    assert_eq(table.total_time_ms, None)
    assert_eq(table.path, ("query_block", "nested_loop", 0, "table"))
    assert_eq(plan.native_json, result.rows[0][0])
    assert_true("attached_condition" in plan.native_json)
    assert_true("secret" in plan.native_json)
    assert_eq(result.format, "json")
    assert_eq(result.analyzed, False)


@test(mark="slow")
async def mariadb_json_analysis_distinguishes_actuals_zero_and_missing_metrics() -> (
    None
):
    """Actual averages, loops and timings are evidence, not fabricated defaults."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        result = await transaction.explain_analyze(
            mariadb.select(MariaAccount).where(MariaAccount.email.eq("missing")),
            format="json",
        )

    plan = result.plan
    assert isinstance(plan, mariadb.MariaDBQueryPlan)
    table = next(node for node in plan.walk() if node.operation == "table")
    assert_eq(table.actual_rows, 1.0)
    assert_eq(table.actual_loops, 1)
    assert_eq(table.actual_filtered_percent, 0.0)
    assert table.table_time_ms is not None
    assert_true(table.table_time_ms >= 0)
    block = next(node for node in plan.walk() if node.operation == "query_block")
    assert block.total_time_ms is not None
    assert_true(block.total_time_ms >= 0)
    assert_eq(block.table_time_ms, None)
    assert_eq(block.estimated_rows, None)
    assert_eq(result.analyzed, True)


@test(
    [Param("estimate", name="estimate"), Param("analyze", name="analyze")],
    mark="slow",
)
async def unsupported_plan_formats_are_rejected(mode: str) -> None:
    """An invalid format must not silently fall back to a different evidence set."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        with assert_raises(mariadb.QueryCompilationError):
            if mode == "analyze":
                await transaction.explain_analyze(
                    mariadb.delete(MariaAccount).all(),
                    format="yaml",  # ty: ignore[invalid-argument-type]
                )
            else:
                await transaction.explain(
                    mariadb.delete(MariaAccount).all(),
                    format="yaml",  # ty: ignore[invalid-argument-type]
                )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email))
    assert_eq(rows, ["secret"])


class PlanPeer:
    """A distinct table role used to retain both sides of a join in a plan."""


@test(mark="slow")
async def mariadb_json_plan_preserves_join_structure_and_native_index_names() -> None:
    """Traversal exposes both table roles; indexed lookup retains its native key."""
    database = await load_fixture(provide_mariadb_accounts())
    peer = mariadb.alias(MariaAccount, PlanPeer, name="peer")
    query = mariadb.select(MariaAccount).left_join(
        peer,
        on=MariaAccount.account_id.eq_col(peer.column(MariaAccount.account_id)),
    )

    async with database.transaction() as transaction:
        joined = await transaction.explain(query, format="json")
        indexed = await transaction.explain(
            mariadb.select(MariaAccount).where(MariaAccount.account_id.eq(7)),
            format="json",
        )

    plan = joined.plan
    assert isinstance(plan, mariadb.MariaDBQueryPlan)
    tables = [node for node in plan.walk() if node.table_name is not None]
    assert_eq({node.table_name for node in tables}, {"maria_account", "peer"})
    assert_true(all(node.path[-1] == "table" for node in tables))
    assert_true(any(node.children for node in plan.roots))
    index_plan = indexed.plan
    assert isinstance(index_plan, mariadb.MariaDBQueryPlan)
    indexed_table = next(node for node in index_plan.walk() if node.table_name)
    assert_eq(indexed_table.key, "PRIMARY")


@test(mark="slow")
async def structured_plan_formatting_and_logging_omit_sensitive_evidence() -> None:
    """Every nested plan repr is safe, not just the outer result's repr."""
    database = await load_fixture(provide_mariadb_accounts())

    with capture_snekql_logs() as logs:
        async with database.transaction() as transaction:
            result = await transaction.explain(
                mariadb.select(MariaAccount).where(
                    MariaAccount.email.eq("private_plan_literal")
                ),
                format="json",
            )
        plan = result.plan
        assert isinstance(plan, mariadb.MariaDBQueryPlan)
        rendered = repr(result) + repr(plan)
        rendered += "".join(repr(node) + str(node) for node in plan.walk())
        rendered += "".join(record.getMessage() for record in logs.records)

    assert_true("private_plan_literal" in plan.native_json)
    assert_eq("private_plan_literal" in rendered, False)
    assert_eq("maria_account" in rendered, False)
    with assert_raises(FrozenInstanceError):
        plan.native_json = "replacement"  # ty: ignore[invalid-assignment]
    table = next(node for node in plan.walk() if node.operation == "table")
    with assert_raises(FrozenInstanceError):
        table.table_name = "replacement"  # ty: ignore[invalid-assignment]


@test(mark="medium")
async def sqlite_json_is_rejected_before_query_io() -> None:
    """An unsupported evidence format is not silently replaced with a native plan."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain(sqlite.select(Account), format="json")


@test(mark="slow")
async def unfamiliar_json_objects_remain_traversable_and_native_values_survive() -> (
    None
):
    """A future server's nested arrays must not hide evidence from traversal."""
    database = await load_fixture(provide_mariadb_accounts())
    native = json.dumps(
        {
            "query_block": {
                "future_operation": [
                    [{"r_loops": 0, "r_rows": 0, "new_metric": "private_future_value"}]
                ]
            }
        }
    )

    # Substitute only the external driver's returned cells, not snekql internals.
    async with database.transaction() as transaction:
        with patch.object(
            MariaCursor, "fetchall", new=AsyncMock(return_value=((native,),))
        ):
            result = await transaction.explain(
                mariadb.select(MariaAccount), format="json"
            )

    plan = result.plan
    assert isinstance(plan, mariadb.MariaDBQueryPlan)
    future = next(node for node in plan.walk() if node.operation == "future_operation")
    assert_eq(future.path, ("query_block", "future_operation", 0, 0))
    assert_eq(future.actual_loops, 0)
    assert_eq(future.actual_rows, 0.0)
    assert_eq(plan.native_json, native)
    assert_eq(result.rows, ((native,),))


@test(mark="medium")
async def malformed_sqlite_parent_links_are_not_silently_dropped() -> None:
    """A cyclic native result cannot masquerade as an empty structured plan."""
    database = await load_fixture(provide_sqlite_accounts())
    rows = ((1, 2, 0, "private_cycle"), (2, 1, 0, "private_cycle"))

    async with database.transaction() as transaction:
        with (
            patch.object(SQLiteCursor, "fetchall", new=AsyncMock(return_value=rows)),
            assert_raises(sqlite.DatabaseRuntimeError) as raised,
        ):
            await transaction.explain(sqlite.select(Account))

    assert_eq("private_cycle" in str(raised.exception), False)


@test(
    [
        Param("private_malformed_json", name="malformed-json"),
        Param('["private_shape"]', name="not-an-object"),
        Param('{"query_block": {"rows": "private_bad_number"}}', name="bad-number"),
        Param('{"query_block": {"rows": true}}', name="boolean-not-number"),
        Param('{"query_block": {"r_rows": NaN}}', name="nonfinite-number"),
        Param('{"query_block": {"r_loops": 1.5}}', name="fractional-loops"),
    ],
    mark="slow",
)
async def malformed_json_plan_errors_omit_native_evidence(native: str) -> None:
    """Validation failures do not echo plan cells or chained JSON parse errors."""
    database = await load_fixture(provide_mariadb_accounts())

    async with database.transaction() as transaction:
        with (
            patch.object(
                MariaCursor, "fetchall", new=AsyncMock(return_value=((native,),))
            ),
            assert_raises(mariadb.DatabaseRuntimeError) as raised,
        ):
            await transaction.explain(mariadb.select(MariaAccount), format="json")

    rendered = "".join(format_exception(raised.exception))
    assert_eq("private_" in rendered, False)
    assert_eq("JSONDecodeError" in rendered, False)
    assert_eq("maria_account" in rendered, False)
