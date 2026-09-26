"""Backend-aware plan inspection through public Transactions."""

from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError
from traceback import format_exception
from typing import ClassVar, Literal

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
        plan = await transaction.explain_analyze(mariadb.select(MariaAccount).all())

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
            sqlite.select(Account.account_id, Account.email).all()
        )

    assert_eq(rows, [(7, "secret")])


@test([Param("update", name="update"), Param("delete", name="delete")], mark="slow")
async def mariadb_explain_does_not_apply_writes(kind: str) -> None:
    """Plain EXPLAIN never opts a write into executing ANALYZE."""
    database = await load_fixture(provide_mariadb_accounts())
    queries = {
        "update": mariadb.update(MariaAccount).set(MariaAccount.email.to("new")).all(),
        "delete": mariadb.delete(MariaAccount).all(),
    }

    async with database.transaction() as transaction:
        await transaction.explain(queries[kind])
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email).all())

    assert_eq(rows, ["secret"])


@test([Param("update", name="update"), Param("delete", name="delete")], mark="slow")
async def analyze_write_commits_on_normal_transaction_exit(kind: str) -> None:
    """Explicit ANALYZE actually applies writes using normal transaction rules."""
    database = await load_fixture(provide_mariadb_accounts())
    queries = {
        "update": mariadb.update(MariaAccount)
        .set(MariaAccount.email.to("changed"))
        .all(),
        "delete": mariadb.delete(MariaAccount).all(),
    }

    async with database.transaction() as transaction:
        await transaction.explain_analyze(queries[kind])
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email).all())

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
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email).all())

    assert_eq(rows, ["secret"])


@test(mark="medium")
async def sqlite_analyze_is_rejected_before_query_io() -> None:
    """SQLite ANALYZE is not an execution-statistics substitute."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain_analyze(sqlite.select(Account).all())


@test(mark="medium")
async def explain_rejects_backend_mismatch_before_query_io() -> None:
    """A wrong-family query fails without looking for its table on SQLite."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.DatabaseRuntimeError) as raised:
            await transaction.explain(mariadb.select(MariaAccount).all())  # ty: ignore[invalid-argument-type]

    assert_eq(type(raised.exception), sqlite.DatabaseRuntimeError)
    assert_true("backend mismatch" in str(raised.exception))


@test(mark="medium")
async def explain_rejects_incomplete_query_before_io() -> None:
    """EXPLAIN preserves the Query Builder's explicit row-scope requirement."""
    async with (
        await sqlite.Database.initialize(database=":memory:") as database,
        database.transaction() as transaction,
    ):
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.explain(sqlite.select(Account))  # ty: ignore[invalid-argument-type]


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
            await transaction.explain(sqlite.select(Account).all())


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
                    await waiter.explain(mariadb.select(MariaAccount).all())
        async with database.transaction() as transaction:
            rows = await transaction.fetch_all(mariadb.select(MariaAccount.email).all())

    assert_eq(rows, ["locked"])


@test([Param("compiled", name="compiled"), Param("raw", name="raw")], mark="medium")
async def explain_accepts_only_built_queries(kind: str) -> None:
    """Arbitrary SQL and inspection snapshots cannot bypass statement policy."""
    queries = {
        "compiled": sqlite.select(Account).all().compile(),
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
        rows = await transaction.fetch_all(mariadb.select(MariaAccount.email).all())

    assert_eq(rows, [email])
