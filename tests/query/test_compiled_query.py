"""Structured SQL inspection through the public Query Builder interface."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql.sqlite import (
    Fetched,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    Text,
    delete,
    insert,
    select,
    update,
)


@test(mark="fast")
def compile_select_preserves_parameter_order() -> None:
    """Compilation keeps values out of SQL without requiring a Database."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        account_id: Account.Col[int] = Integer(primary_key=True)
        email: Account.Col[str] = Text()

    compiled = (
        select(Account.email)
        .where(Account.account_id.gt(7), Account.email.eq("o'hara@example.com"))
        .compile()
    )

    assert_eq(
        compiled.sql,
        'SELECT "email" FROM "account" WHERE ("account_id" > ?) AND ("email" = ?)',
    )
    assert_eq(compiled.params, (7, "o'hara@example.com"))
    assert_eq(compiled.backend, "sqlite")


@test(mark="fast")
def compiled_text_redacts_bound_values() -> None:
    """The structured result is safe to format without printing bindings."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    compiled = select(Account).where(Account.email.eq("private@example.com")).compile()

    assert_eq(
        repr(compiled),
        "CompiledQuery(backend='sqlite', params=<redacted:1>, "
        'sql=\'SELECT "email" FROM "account" WHERE ("email" = ?)\')',
    )
    assert_eq(str(compiled), repr(compiled))
    assert_eq(compiled.params, ("private@example.com",))


@test(mark="fast")
def compiled_type_is_exported_by_backend_namespaces() -> None:
    """Integrations can annotate compiled output without private imports."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    compiled: sqlite.CompiledQuery = select(Account).all().compile()

    assert_eq(type(compiled), sqlite.CompiledQuery)
    assert_eq(sqlite.CompiledQuery, mariadb.CompiledQuery)


@test(mark="fast")
def compile_mariadb_uses_native_placeholders() -> None:
    """MariaDB compilation uses its own Dialect without a server."""

    class Account[S = mariadb.Pending](mariadb.Model[S, "Account[mariadb.Fetched]"]):
        email: Account.Col[str] = mariadb.Text(primary_key=True)

    compiled = mariadb.select(Account.email).where(Account.email.eq("secret")).compile()

    assert_eq(compiled.sql, "SELECT `email` FROM `account` WHERE (`email` = %s)")
    assert_eq(compiled.params, ("secret",))
    assert_eq(compiled.backend, "mariadb")


@test(
    [
        Param("backend", name="backend"),
        Param("params", name="params"),
        Param("sql", name="sql"),
    ],
    mark="fast",
)
def compiled_fields_are_frozen(field_name: str) -> None:
    """Public fields cannot be rebound after compilation."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    compiled = select(Account).all().compile()

    with assert_raises(FrozenInstanceError):
        setattr(compiled, field_name, "replacement")


@test(mark="fast")
def compile_insert_returns_encoded_bindings() -> None:
    """Insert parameters contain the Dialect wire form, not Python input."""

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        event_id: Event.Col[int] = Integer(primary_key=True)
        occurred_at: Event.Col[sqlite.UtcDatetime] = Text()

    compiled = insert(
        Event(event_id=3, occurred_at=datetime(2026, 1, 2, tzinfo=UTC))
    ).compile()

    assert_eq(
        compiled.sql, 'INSERT INTO "event" ("event_id", "occurred_at") VALUES (?, ?)'
    )
    assert_eq(compiled.params, (3, "2026-01-02T00:00:00.000Z"))


@test(mark="fast")
def compile_update_returning_preserves_assignment_order() -> None:
    """Returning writes compile SQL only, without result materialization policy."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        account_id: Account.Col[int] = Integer(primary_key=True)
        email: Account.Col[str] = Text()

    compiled = (
        update(Account)
        .set(Account.email.to("new"))
        .where(Account.account_id.eq(7))
        .returning(Account.email)
        .compile()
    )

    assert_eq(
        compiled.sql,
        'UPDATE "account" SET "email" = ? WHERE ("account_id" = ?) RETURNING "email"',
    )
    assert_eq(compiled.params, ("new", 7))


@test(mark="fast")
def compile_delete_preserves_row_scope() -> None:
    """Delete compilation retains the explicit predicate."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    compiled = delete(Account).where(Account.email.eq("old")).compile()

    assert_eq(compiled.sql, 'DELETE FROM "account" WHERE ("email" = ?)')
    assert_eq(compiled.params, ("old",))


@test(mark="fast")
def compile_bulk_insert_preserves_row_order() -> None:
    """Bulk compilation exposes one statement with bindings in row order."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    compiled = insert([Account(email="first"), Account(email="second")]).compile()

    assert_eq(compiled.sql, 'INSERT INTO "account" ("email") VALUES (?), (?)')
    assert_eq(compiled.params, ("first", "second"))


@test(
    [
        Param("select", name="select"),
        Param("delete", name="delete"),
        Param("update-unassigned", name="update-unassigned"),
        Param("update-unscoped", name="update-unscoped"),
        Param("empty-insert", name="empty-insert"),
    ],
    mark="fast",
)
def compile_rejects_incomplete_queries(kind: str) -> None:
    """Compilation raises instead of returning the debug incomplete string."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    queries = {
        "select": select(Account),
        "delete": delete(Account),
        "update-unassigned": update(Account).all(),
        "update-unscoped": update(Account).set(Account.email.to("new")),
        "empty-insert": insert([]),
    }

    with assert_raises(QueryCompilationError):
        queries[kind].compile()


@test(mark="fast")
def compiled_output_is_a_snapshot_of_query_state() -> None:
    """Later builder transitions cannot change an existing compiled result."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    query = select(Account).where(Account.email.eq("old"))
    compiled = query.compile()
    query = query.where(Account.email.eq("new"))

    assert_eq(compiled.sql, 'SELECT "email" FROM "account" WHERE ("email" = ?)')
    assert_eq(compiled.params, ("old",))
    assert_eq(query.compile().params, ("old", "new"))


@test(mark="fast")
def compile_cannot_retarget_a_model_to_another_backend() -> None:
    """Dynamic callers cannot compile a SQLite model through MariaDB verbs."""

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    with assert_raises(sqlite.QueryConstructionError):
        # Deliberately cross Backend Families to exercise the runtime guard.
        mariadb.select(Account).all().compile()  # ty: ignore[no-matching-overload]


@test(mark="medium")
async def transaction_rejects_compiled_inspection_output() -> None:
    """Compiled output is not a raw statement or an executable Query Builder."""
    async with await sqlite.Database.initialize(database=":memory:") as database:

        class Account[S = Pending](Model[S, "Account[Fetched]"]):
            email: Account.Col[str] = Text(primary_key=True)

        compiled = select(Account).all().compile()

        async with database.transaction() as transaction:
            with assert_raises(QueryCompilationError):
                # Deliberately bypass typing to check the inspection-only contract.
                await transaction.fetch_all(compiled)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def compile_is_available_through_select_annotation() -> None:
    """Helpers accepting Select can compile without naming concrete builders."""

    def inspect(query: sqlite.Select[str]) -> sqlite.CompiledQuery:
        return query.compile()

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    assert_eq(inspect(select(Account.email).all()).params, ())


@test(mark="fast")
def compile_is_available_through_write_annotation() -> None:
    """Helpers accepting Write can compile without naming concrete builders."""

    def inspect(query: sqlite.Write[int]) -> sqlite.CompiledQuery:
        return query.compile()

    class Account[S = Pending](Model[S, "Account[Fetched]"]):
        email: Account.Col[str] = Text(primary_key=True)

    assert_eq(inspect(delete(Account).all()).sql, 'DELETE FROM "account"')
