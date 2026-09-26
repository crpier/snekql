"""Query-object SQL inspection through ``repr()``/``str()``.

A built query renders its own backend Dialect SQL for debugging, resolving the
dialect from its model's backend with no Database/Transaction. ``repr`` is a
compact parameterized line; ``str`` hides bindings too. Explicit value
inspection adds an approximate inlined form.
"""

from __future__ import annotations

from typing import ClassVar

from snektest import assert_eq, test

from snekql.sqlite import (
    PENDING_GENERATION,
    Integer,
    Model,
    Pending,
    ReadType,
    Row,
    Text,
    delete,
    insert,
    select,
    update,
)
from tests.helpers import SQLITE_CODEC


class User[S = Pending](Model[S]):
    """Table model used across the SQL-inspection tests."""

    __row_type__: ClassVar[ReadType[User[Row]]]

    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = Text(nullable=False)
    age: User.Col[int] = Integer(nullable=False)


@test(mark="fast")
def repr_renders_parameterized_select_sql() -> None:
    """``repr`` shows parameterized SQL and the binding count on one line."""

    query = select(User).where(User.age.gt(18))
    sql, params = SQLITE_CODEC.compile_select_sql(query)

    assert_eq(
        repr(query), f"<SelectModelQuery: {sql} | params=<redacted:{len(params)}>>"
    )
    assert_eq(params, (18,))


@test(mark="fast")
def explicit_inspection_includes_inlined_form() -> None:
    """Explicit value inspection shows both SQL forms for local diagnostics."""

    query = select(User).where(User.email.eq("a@b.com"), User.age.gt(18))
    rendered = query.inspect(parameter_visibility="values")

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
    sql, _params = SQLITE_CODEC.compile_select_sql(query)

    assert_eq('("age" > ?)' in sql, True)
    assert_eq('("email" = ?)' in sql, True)
    assert_eq(sql in repr(query), True)


@test(mark="fast")
def incomplete_select_repr_degrades_without_raising() -> None:
    """A select missing ``all()``/``where()`` reprs as incomplete, never raises."""

    rendered = repr(select(User))

    assert_eq(rendered, "<SelectModelQuery inspection unavailable>")
    assert_eq(str(select(User)), "<SelectModelQuery inspection unavailable>")


@test(mark="fast")
def update_and_delete_repr_render_write_sql() -> None:
    """Update and delete queries render their write SQL through ``repr``."""

    update_query = update(User).set(User.age.to(21)).where(User.id.eq(1))
    update_sql, update_params = SQLITE_CODEC.compile_write_sql(update_query)
    assert_eq(
        repr(update_query),
        f"<UpdateQuery: {update_sql} | params=<redacted:{len(update_params)}>>",
    )

    delete_query = delete(User).where(User.id.eq(1))
    delete_sql, delete_params = SQLITE_CODEC.compile_write_sql(delete_query)
    assert_eq(
        repr(delete_query),
        f"<DeleteQuery: {delete_sql} | params=<redacted:{len(delete_params)}>>",
    )


@test(mark="fast")
def insert_repr_renders_values_sql() -> None:
    """An insert query renders its ``INSERT`` SQL through ``repr``."""

    insert_query = insert(User(email="a@b.com", age=18))
    sql, params = SQLITE_CODEC.compile_write_sql(insert_query)

    assert_eq(
        repr(insert_query), f"<InsertQuery: {sql} | params=<redacted:{len(params)}>>"
    )
