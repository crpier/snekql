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
    compiled = query.compile()
    expected_sql = 'SELECT "id", "email", "age" FROM "user" WHERE ("age" > ?)'

    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, (18,))
    assert_eq(repr(query), f"<SelectModelQuery: {expected_sql} | params=<redacted:1>>")


@test(mark="fast")
def explicit_inspection_includes_inlined_form() -> None:
    """Explicit value inspection shows both SQL forms for local diagnostics."""

    query = select(User).where(User.email.eq("a@b.com"), User.age.gt(18))
    rendered = query.inspect(parameter_visibility="values")

    expected_sql = (
        'SELECT "id", "email", "age" FROM "user" WHERE ("email" = ?) AND ("age" > ?)'
    )
    expected_inlined = (
        'SELECT "id", "email", "age" FROM "user" '
        """WHERE ("email" = 'a@b.com') AND ("age" > 18)"""
    )

    assert_eq(
        rendered,
        "-- parameterized (executes):\n"
        f"{expected_sql}\n"
        "-- params: ('a@b.com', 18)\n"
        "\n"
        "-- inlined literals (approximate, not executed):\n"
        f"{expected_inlined}",
    )


@test(mark="fast")
def composed_query_repr_reflects_final_state() -> None:
    """Re-binding ``query = query.where(...)`` accumulates into the rendered SQL."""

    query = select(User).where(User.age.gt(18))
    query = query.where(User.email.eq("a@b.com"))
    compiled = query.compile()
    expected_sql = (
        'SELECT "id", "email", "age" FROM "user" WHERE ("age" > ?) AND ("email" = ?)'
    )

    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, (18, "a@b.com"))
    assert_eq(repr(query), f"<SelectModelQuery: {expected_sql} | params=<redacted:2>>")


@test(mark="fast")
def bare_select_repr_renders_sql() -> None:
    """A bare SELECT renders through the normal redacted inspection path."""

    expected_sql = 'SELECT "id", "email", "age" FROM "user"'
    expected_repr = f"<SelectModelQuery: {expected_sql} | params=<redacted:0>>"
    expected_text = (
        f"-- parameterized (executes):\n{expected_sql}\n-- params: <redacted:0>"
    )

    for query in (select(User), select(User)):
        assert_eq(repr(query), expected_repr)
        assert_eq(str(query), expected_text)
        assert_eq(query.inspect(), expected_text)


@test(mark="fast")
def update_and_delete_repr_render_write_sql() -> None:
    """Update and delete queries render their write SQL through ``repr``."""

    update_query = update(User).set(User.age.to(21)).where(User.id.eq(1))
    compiled_update = update_query.compile()
    expected_update_sql = 'UPDATE "user" SET "age" = ? WHERE ("id" = ?)'
    assert_eq(compiled_update.sql, expected_update_sql)
    assert_eq(compiled_update.params, (21, 1))
    assert_eq(
        repr(update_query),
        f"<UpdateQuery: {expected_update_sql} | params=<redacted:2>>",
    )

    delete_query = delete(User).where(User.id.eq(1))
    compiled_delete = delete_query.compile()
    expected_delete_sql = 'DELETE FROM "user" WHERE ("id" = ?)'
    assert_eq(compiled_delete.sql, expected_delete_sql)
    assert_eq(compiled_delete.params, (1,))
    assert_eq(
        repr(delete_query),
        f"<DeleteQuery: {expected_delete_sql} | params=<redacted:1>>",
    )


@test(mark="fast")
def insert_repr_renders_values_sql() -> None:
    """An insert query renders its ``INSERT`` SQL through ``repr``."""

    insert_query = insert(User(email="a@b.com", age=18))
    compiled = insert_query.compile()
    expected_sql = 'INSERT INTO "user" ("email", "age") VALUES (?, ?)'

    assert_eq(compiled.sql, expected_sql)
    assert_eq(compiled.params, ("a@b.com", 18))
    assert_eq(
        repr(insert_query), f"<InsertQuery: {expected_sql} | params=<redacted:2>>"
    )
