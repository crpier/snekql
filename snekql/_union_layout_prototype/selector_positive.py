"""Check selector-based layout precision with no runtime implementation."""

from typing import assert_type

from selector import Expr, Fields, Query, integer, optional_integer, optional_text, text

left = Query(Fields(event_id=integer(), title=text()))
right = Query(Fields(title=text(), event_id=optional_integer()))
combined = left.union_all(right)
assert_type(combined.column(lambda fields: fields.event_id), Expr[int | None])
assert_type(combined.column(lambda fields: fields.title), Expr[str])
assert_type(left.union_all(left).column(lambda fields: fields.event_id), Expr[int])
assert_type(
    right.union_all(left).column(lambda fields: fields.event_id), Expr[int | None]
)
third = Query(Fields(event_id=integer(), title=optional_text()))
assert_type(
    combined.union_all(third).column(lambda fields: fields.title), Expr[str | None]
)


def helper(
    query: Query[Fields[int, str]], other: Query[Fields[int | None, str]]
) -> Expr[int | None]:
    """A helper retains precise field-level optionality."""
    return query.union_all(other).column(lambda fields: fields.event_id)
