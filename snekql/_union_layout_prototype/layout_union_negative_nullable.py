"""Required consumers cannot erase nullable right-hand fields."""

from layout_union import Fields, integer, optional_integer, project, text, value

left = project(Fields(event_id=integer(), title=text()))
right = project(Fields(event_id=optional_integer(), title=text()))
required: int = value(left.union_all(right).columns.event_id)
