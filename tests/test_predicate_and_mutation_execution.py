"""Predicate intent, immutable builders, and mutation execution tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from sqlite3 import connect
from tempfile import TemporaryDirectory
from typing import cast

from snektest import assert_eq, assert_is, assert_ne, assert_raises, test

from snekql import (
    MISSING,
    Database,
    Integer,
    Model,
    Pending,
    QueryCompilationError,
    QueryConstructionError,
    Text,
    delete,
    insert,
    select,
    update,
)
from snekql.query import compile_select_sql, compile_write_sql
from tests.logging_helpers import NULL_LOGGER


def _fetch_rows(database_path: Path, sql: str) -> list[tuple[object, ...]]:
    connection = connect(database_path)
    try:
        cursor = connection.execute(sql)
        return [tuple(row) for row in cursor.fetchall()]
    finally:
        connection.close()


@test(mark="fast")
def predicates_reject_ambiguous_or_invalid_intent() -> None:
    """Predicate helpers reject null ambiguity, empty IN, and non-text LIKE."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by predicate construction checks."""

        id: User.Col[int] = Integer(nullable=False)
        email: User.Col[str] = Text(nullable=False)

    email_eq = cast("Callable[[object], object]", User.email.eq)
    email_ne = cast("Callable[[object], object]", User.email.ne)
    email_not_in = cast("Callable[..., object]", User.email.not_in)

    with assert_raises(QueryConstructionError):
        _ = email_eq(None)

    with assert_raises(QueryConstructionError):
        _ = email_ne(None)

    with assert_raises(QueryConstructionError):
        _ = User.email.in_()

    with assert_raises(QueryConstructionError):
        _ = email_not_in("a@example.com", None)

    with assert_raises(QueryConstructionError):
        _ = User.id.like("1%")


@test(mark="fast")
def select_builders_are_immutable_and_require_filter_intent() -> None:
    """Select chain methods return new queries except repeated all() no-ops."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by immutable select checks."""

        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    base_query = select(User.email)
    filtered_query = base_query.where(User.status.eq("active"))
    ordered_query = filtered_query.order_by(User.email.asc())
    paged_query = ordered_query.limit(10).limit(2).offset(1)
    all_query = base_query.all()

    assert_ne(filtered_query, base_query)
    assert_ne(ordered_query, filtered_query)
    assert_is(all_query.all(), all_query)

    with assert_raises(QueryConstructionError):
        _ = base_query.where()

    with assert_raises(QueryConstructionError):
        _ = base_query.order_by()

    with assert_raises(QueryConstructionError):
        _ = all_query.where(User.status.eq("active"))

    with assert_raises(QueryConstructionError):
        _ = filtered_query.all()

    with assert_raises(QueryCompilationError):
        _ = compile_select_sql(base_query)

    with assert_raises(QueryCompilationError):
        _ = compile_write_sql(all_query)

    sql, params = compile_select_sql(paged_query)

    expected_sql = (
        'SELECT "email" FROM "user" WHERE ("status" = ?) '
        'ORDER BY "email" ASC LIMIT ? OFFSET ?'
    )
    assert_eq(sql, expected_sql)
    assert_eq(params, ("active", 2, 1))


@test(mark="fast")
def update_compilation_requires_set_and_filter_intent() -> None:
    """Update SQL is parameterized and refuses implicit full-table updates."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by update compilation checks."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    base_query = update(User)
    set_query = base_query.set(User.status.to("disabled"))
    filtered_query = set_query.where(User.email.eq("old@example.com"))

    assert_ne(set_query, base_query)
    assert_ne(filtered_query, set_query)

    with assert_raises(QueryConstructionError):
        _ = base_query.set()

    with assert_raises(QueryConstructionError):
        _ = set_query.all().where(User.email.eq("old@example.com"))

    with assert_raises(QueryConstructionError):
        _ = filtered_query.all()

    with assert_raises(QueryConstructionError):
        _ = update(User).set(User.id.to(2))

    all_query = set_query.all()
    assert_is(all_query.all(), all_query)
    assert_eq(
        compile_write_sql(all_query),
        ('UPDATE "user" SET "status" = ?', ("disabled",)),
    )

    with assert_raises(QueryCompilationError):
        _ = compile_write_sql(base_query.all())

    with assert_raises(QueryCompilationError):
        _ = compile_write_sql(set_query)

    sql, params = compile_write_sql(filtered_query)

    assert_eq(sql, 'UPDATE "user" SET "status" = ? WHERE ("email" = ?)')
    assert_eq(params, ("disabled", "old@example.com"))


@test(mark="fast")
def delete_compilation_requires_filter_intent() -> None:
    """Delete SQL requires explicit where() or all() before compilation."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by delete compilation checks."""

        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    base_query = delete(User)
    filtered_query = base_query.where(
        User.status.eq("disabled"),
        User.email.like("%@example.com"),
    )
    all_query = base_query.all()

    assert_ne(filtered_query, base_query)
    assert_is(all_query.all(), all_query)

    with assert_raises(QueryConstructionError):
        _ = base_query.where()

    with assert_raises(QueryConstructionError):
        _ = all_query.where(User.status.eq("disabled"))

    with assert_raises(QueryConstructionError):
        _ = filtered_query.all()

    with assert_raises(QueryCompilationError):
        _ = compile_write_sql(base_query)

    sql, params = compile_write_sql(filtered_query)

    expected_sql = 'DELETE FROM "user" WHERE ("status" = ?) AND ("email" LIKE ?)'
    assert_eq(sql, expected_sql)
    assert_eq(params, ("disabled", "%@example.com"))
    assert_eq(compile_write_sql(all_query), ('DELETE FROM "user"', ()))


@test(mark="medium")
async def update_and_delete_execute_against_sqlite() -> None:
    """Mutation queries persist changes through the async transaction runtime."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by mutation execution checks."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "app.db"
        database = await Database.initialize(
            NULL_LOGGER, database=database_path, models=[User]
        )
        try:
            async with database.transaction() as transaction:
                await transaction.execute(insert(User(email="a@example.com")))
                await transaction.execute(insert(User(email="b@example.com")))
                await transaction.execute(
                    update(User)
                    .set(User.status.to("disabled"))
                    .where(User.email.eq("a@example.com")),
                )
                await transaction.execute(
                    delete(User).where(User.status.eq("active")),
                )
        finally:
            await database.close()

        rows = _fetch_rows(
            database_path,
            'SELECT "email", "status" FROM "user" ORDER BY "email"',
        )

    assert_eq(rows, [("a@example.com", "disabled")])
