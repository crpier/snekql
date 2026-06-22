"""Query-object SQL inspection through ``repr()``/``str()``.

A built query renders its own backend Dialect SQL for debugging, resolving the
dialect from its model's backend with no Database/Transaction. ``repr`` is a
compact parameterized line; ``str`` adds an inlined-literals form. Neither
raises on an incomplete query.
"""

from __future__ import annotations

from snektest import assert_eq, test

from snekql.sqlite import (
    MISSING,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
    delete,
    insert,
    select,
    update,
)
from snekql.sqlite.query import compile_sqlite_select_sql, compile_sqlite_write_sql


class User[S = Pending](Model[S, "User[Fetched]"]):
    """Table model used across the SQL-inspection tests."""

    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False)
    age: User.Col[int] = Integer(nullable=False)


@test(mark="fast")
def repr_renders_parameterized_select_sql() -> None:
    """``repr`` shows the parameterized SQL and the bound params on one line."""

    query = select(User).where(User.age.gt(18))
    sql, params = compile_sqlite_select_sql(query)

    assert_eq(repr(query), f"<SelectModelQuery: {sql} | params={params!r}>")
    assert_eq(params, (18,))


@test(mark="fast")
def str_includes_parameterized_and_inlined_forms() -> None:
    """``str`` shows the executing form and an approximate inlined form."""

    query = select(User).where(User.email.eq("a@b.com"), User.age.gt(18))
    rendered = str(query)

    assert_eq("-- parameterized (executes):" in rendered, True)
    assert_eq('("email" = ?)' in rendered, True)
    assert_eq("-- inlined literals (approximate, not executed):" in rendered, True)
    assert_eq("""("email" = 'a@b.com')""" in rendered, True)
    assert_eq('("age" > 18)' in rendered, True)


@test(mark="fast")
def composed_query_repr_reflects_final_state() -> None:
    """Re-binding ``query = query.where(...)`` accumulates into the rendered SQL."""

    query = select(User).where(User.age.gt(18))
    query = query.where(User.email.eq("a@b.com"))
    sql, _params = compile_sqlite_select_sql(query)

    assert_eq('("age" > ?)' in sql, True)
    assert_eq('("email" = ?)' in sql, True)
    assert_eq(sql in repr(query), True)


@test(mark="fast")
def incomplete_select_repr_degrades_without_raising() -> None:
    """A select missing ``all()``/``where()`` reprs as incomplete, never raises."""

    rendered = repr(select(User))

    assert_eq(rendered.startswith("<SelectModelQuery incomplete: "), True)
    assert_eq("all()" in rendered, True)
    # str must not raise either.
    assert_eq(str(select(User)).startswith("<SelectModelQuery incomplete: "), True)


@test(mark="fast")
def update_and_delete_repr_render_write_sql() -> None:
    """Update and delete queries render their write SQL through ``repr``."""

    update_query = update(User).set(User.age.to(21)).where(User.id.eq(1))
    update_sql, update_params = compile_sqlite_write_sql(update_query)
    assert_eq(
        repr(update_query),
        f"<UpdateQuery: {update_sql} | params={update_params!r}>",
    )

    delete_query = delete(User).where(User.id.eq(1))
    delete_sql, delete_params = compile_sqlite_write_sql(delete_query)
    assert_eq(
        repr(delete_query),
        f"<DeleteQuery: {delete_sql} | params={delete_params!r}>",
    )


@test(mark="fast")
def insert_repr_renders_values_sql() -> None:
    """An insert query renders its ``INSERT`` SQL through ``repr``."""

    insert_query = insert(User(email="a@b.com", age=18))
    sql, params = compile_sqlite_write_sql(insert_query)

    assert_eq(repr(insert_query), f"<InsertQuery: {sql} | params={params!r}>")
