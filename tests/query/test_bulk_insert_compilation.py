"""Bulk insert and RETURNING SQL compilation tests."""

from __future__ import annotations

from snektest import assert_eq, assert_raises, test

from snekql.sqlite import (
    MISSING,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    Text,
    insert,
)
from snekql.sqlite.query import compile_sqlite_write_sql


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model with a generated primary key and explicit columns."""

    id: User.GenCol[int] = Integer(
        primary_key=True, auto_increment=True, default=MISSING
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")


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
