"""Bulk insert and RETURNING SQL compilation tests."""

from __future__ import annotations

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    Text,
    insert,
)
from snekql.sqlite.query import compile_sqlite_write_sql


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model with a generated primary key and explicit columns."""

    id: User.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")


class Account[S = Pending](Model[S, "Account[Fetched]"]):
    """Unrelated table model, used to test cross-model returning rejection."""

    id: Account.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=PENDING_GENERATION
    )
    name: Account.Col[str] = Text(nullable=False)


@test(mark="fast")
def single_returning_appends_all_columns_in_declaration_order() -> None:
    """A single insert with returning() lists every column after RETURNING."""

    sql, params = compile_sqlite_write_sql(
        insert(User(email="a@example.com")).returning()
    )

    expected = 'INSERT INTO "user" ("email", "status") VALUES (?, ?)'
    expected += ' RETURNING "id", "email", "status"'
    assert_eq(sql, expected)
    assert_eq(params, ("a@example.com", "active"))


@test(mark="fast")
def single_returning_columns_lists_only_named_columns() -> None:
    """returning(col, col) lists just those columns after RETURNING, in order."""

    sql, params = compile_sqlite_write_sql(
        insert(User(email="a@example.com")).returning(User.id, User.email)
    )

    expected = 'INSERT INTO "user" ("email", "status") VALUES (?, ?)'
    expected += ' RETURNING "id", "email"'
    assert_eq(sql, expected)
    assert_eq(params, ("a@example.com", "active"))


@test(mark="fast")
def bulk_returning_columns_lists_only_named_columns_once() -> None:
    """A bulk returning projection appends one RETURNING clause for the batch."""

    sql, _ = compile_sqlite_write_sql(
        insert(
            [
                User(email="a@example.com"),
                User(email="b@example.com"),
            ]
        ).returning(User.id)
    )

    expected = 'INSERT INTO "user" ("email", "status") VALUES (?, ?), (?, ?)'
    expected += ' RETURNING "id"'
    assert_eq(sql, expected)


@test(mark="fast")
def returning_rejects_a_column_from_another_model() -> None:
    """A returning projection must name columns of the inserted model."""

    with assert_raises(QueryConstructionError):
        # A column from another model is also a static error (the owner is pinned
        # to the written model); the runtime guard is what this test exercises.
        _ = insert(User(email="a@example.com")).returning(Account.name)  # pyright: ignore[reportArgumentType]


@test(mark="fast")
def bulk_insert_compiles_one_multi_row_values_statement() -> None:
    """A bulk insert flattens homogeneous rows into one VALUES list."""

    sql, params = compile_sqlite_write_sql(
        insert(
            [
                User(email="a@example.com", status="active"),
                User(email="b@example.com", status="invited"),
            ]
        )
    )

    assert_eq(
        sql,
        'INSERT INTO "user" ("email", "status") VALUES (?, ?), (?, ?)',
    )
    assert_eq(params, ("a@example.com", "active", "b@example.com", "invited"))


@test(mark="fast")
def bulk_insert_returning_appends_columns_once() -> None:
    """Bulk returning appends a single RETURNING clause for the whole statement."""

    sql, params = compile_sqlite_write_sql(
        insert(
            [
                User(email="a@example.com", status="active"),
                User(email="b@example.com", status="active"),
            ]
        ).returning()
    )

    expected = 'INSERT INTO "user" ("email", "status") VALUES (?, ?), (?, ?)'
    expected += ' RETURNING "id", "email", "status"'
    assert_eq(sql, expected)
    assert_eq(
        params,
        ("a@example.com", "active", "b@example.com", "active"),
    )


@test(mark="fast")
def bulk_insert_rejects_heterogeneous_column_sets() -> None:
    """Rows that set different columns cannot share one VALUES statement."""

    query = insert(
        [
            User(id=1, email="a@example.com", status="active"),
            User(email="b@example.com", status="active"),
        ]
    )

    with assert_raises(QueryCompilationError):
        _ = compile_sqlite_write_sql(query)
