"""Keep a union of whole layouts rather than computing a mapped type."""

from typing import assert_type

from layout_union import (
    EventSchema,
    Fields,
    Query,
    integer,
    optional_integer,
    optional_text,
    project,
    text,
    value,
)

left = project(Fields(event_id=integer(), title=text()))
right = project(Fields(title=text(), event_id=optional_integer()))
combined = left.union_all(right)
assert_type(value(combined.columns.event_id), int | None)
assert_type(value(combined.columns.title), str)
assert_type(value(left.union_all(left).columns.event_id), int)
assert_type(value(right.union_all(left).columns.event_id), int | None)
third = project(Fields(event_id=integer(), title=optional_text()))
assert_type(value(combined.union_all(third).columns.title), str | None)
assert_type(value(left.union(right.union_all(third)).columns.event_id), int | None)


def helper(
    query: Query[EventSchema, Fields[int, str]],
    other: Query[EventSchema, Fields[int | None, str]],
) -> int | None:
    """Helper inputs retain the typed layout, with no result-specific union method."""
    return value(query.union_all(other).columns.event_id)
