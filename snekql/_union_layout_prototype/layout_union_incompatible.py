"""Must reject incompatible logical domains at composition, not fetching."""

from layout_union import Fields, integer, project, text

left = project(Fields(event_id=integer(), title=text()))
wrong = project(Fields(event_id=text(), title=text()))
left.union_all(wrong)
