"""Delete query construction, compilation, and execution acceptance tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from snektest import (
    assert_eq,
    assert_is,
    assert_is_none,
    assert_ne,
    assert_raises,
    test,
)

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
)
from snekql.query import compile_write_sql


@test(mark="fast")
def delete_compilation_quotes_identifiers_and_parameterizes_filters() -> None:
    """Delete compiles quoted table and column names with bound parameters."""

    class Order[S = Pending](Model[S, "Order[object]"]):
        """Table model with identifiers requiring SQLite quoting."""

        __tablename__ = "select"
        status: Order.Col[str] = Text(nullable=False)
        where: Order.Col[str] = Text(nullable=False)

    query = delete(Order).where(
        Order.where.ne("old"),
        Order.status.eq("done"),
    )

    sql, params = compile_write_sql(query)

    expected_sql = 'DELETE FROM "select" WHERE ("where" != ?) AND ("status" = ?)'
    assert_eq(sql, expected_sql)
    assert_eq(params, ("old", "done"))


@test(mark="fast")
def delete_predicates_must_belong_to_target_model() -> None:
    """Delete where() rejects predicates built from another table model."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Target table model for ownership checks."""

        email: User.Col[str] = Text(nullable=False)

    class AuditLog[S = Pending](Model[S, "AuditLog[object]"]):
        """Unrelated table model for ownership checks."""

        message: AuditLog.Col[str] = Text(nullable=False)

    where = cast("Callable[..., object]", delete(User).where)

    with assert_raises(QueryConstructionError):
        _ = where(AuditLog.message.eq("wrong table"))


@test(mark="fast")
def delete_requires_exactly_one_filter_intent() -> None:
    """Delete requires exactly one of where() or all() before compilation."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model used by explicit delete intent checks."""

        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False)

    base_query = delete(User)
    filtered_query = base_query.where(User.status.eq("disabled"))
    all_query = base_query.all()

    assert_ne(filtered_query, base_query)
    assert_is(all_query.all(), all_query)

    with assert_raises(QueryConstructionError):
        _ = base_query.where()

    with assert_raises(QueryConstructionError):
        _ = filtered_query.all()

    with assert_raises(QueryConstructionError):
        _ = all_query.where(User.status.eq("disabled"))

    with assert_raises(QueryCompilationError):
        _ = compile_write_sql(base_query)

    assert_eq(compile_write_sql(all_query), ('DELETE FROM "user"', ()))


@test(mark="medium")
async def delete_execute_returns_none_for_filtered_and_explicit_all_forms() -> None:
    """tx.execute(delete(...)) returns None for filtered and full-table deletes."""

    class User[S = Pending](Model[S, "User[object]"]):
        """Table model deleted through the async runtime."""

        id: User.GenCol[int] = Integer(primary_key=True, default=MISSING)
        email: User.Col[str] = Text(nullable=False)
        status: User.Col[str] = Text(nullable=False, default="active")

    database = await Database.initialize(database=":memory:", models=[User])
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="a@example.com")))
            await transaction.execute(
                insert(User(email="b@example.com", status="disabled")),
            )

            filtered_result = await transaction.execute(
                delete(User).where(User.status.eq("disabled")),
            )
            remaining_after_filtered = await transaction.fetch_all(
                select(User.email).all().order_by(User.email.asc()),
            )
            all_result = await transaction.execute(delete(User).all())
            remaining_after_all = await transaction.fetch_all(select(User.email).all())
    finally:
        await database.close()

    assert_is_none(filtered_result)
    assert_eq(remaining_after_filtered, ["a@example.com"])
    assert_is_none(all_result)
    assert_eq(remaining_after_all, [])
