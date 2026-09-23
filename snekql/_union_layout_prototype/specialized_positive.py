"""Precise fieldwise unions using a query type specialized to one schema."""

from typing import assert_type

from specialized import (
    ID,
    TITLE,
    Events,
    Expr,
    SQLite,
    integer,
    optional_integer,
    optional_text,
    project,
    text,
)

left = project(SQLite, event_id=integer(), title=text())
right = project(SQLite, title=text(), event_id=optional_integer())
combined = left.union_all(right)
assert_type(combined.column(ID), Expr[int | None])
assert_type(combined.column(TITLE), Expr[str])
assert_type(combined.columns.event_id, Expr[int | None])
assert_type(left.union_all(left).column(ID), Expr[int])
assert_type(right.union_all(left).column(ID), Expr[int | None])
third = project(SQLite, event_id=integer(), title=optional_text())
assert_type(combined.union_all(third).column(TITLE), Expr[str | None])
assert_type(left.union(right.union_all(third)).column(ID), Expr[int | None])


def helper(
    query: Events[SQLite, int, str], other: Events[SQLite, int | None, str]
) -> Expr[int | None]:
    """Public helper annotations need no casts or loss of output precision."""
    return query.union_all(other).column(ID)
