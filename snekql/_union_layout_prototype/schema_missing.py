"""Must reject missing output fields at composition."""

from schema import DifferentFields, Fields, integer, project, text

left = project(Fields(event_id=integer(), title=text()))
wrong = project(DifferentFields(event_id=integer()))
left.union_all(wrong)
