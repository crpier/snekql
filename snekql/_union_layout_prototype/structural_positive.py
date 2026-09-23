"""Precise field access through reordered and nested compound schemas."""

from typing import assert_type

from structural import (
    Fields,
    IdKey,
    Slot,
    TitleKey,
    integer,
    optional_integer,
    optional_text,
    project,
    text,
)

left = project(Fields(event_id=integer(), title=text()))
right = project(Fields(title=text(), event_id=optional_integer()))
combined = left.union_all(right)
assert_type(combined.column(lambda fields: fields.event_id), Slot[IdKey, int | None])
assert_type(combined.column(lambda fields: fields.title), Slot[TitleKey, str])
assert_type(
    left.union_all(left).column(lambda fields: fields.event_id), Slot[IdKey, int]
)
assert_type(
    right.union_all(left).column(lambda fields: fields.event_id),
    Slot[IdKey, int | None],
)
third = project(Fields(event_id=integer(), title=optional_text()))
assert_type(
    combined.union_all(third).column(lambda fields: fields.title),
    Slot[TitleKey, str | None],
)
