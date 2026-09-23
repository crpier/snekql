"""Must reject missing output fields at composition."""

from selector import DifferentFields, Fields, Query, integer, text

left = Query(Fields(event_id=integer(), title=text()))
wrong = Query(DifferentFields(event_id=integer()))
left.union_all(wrong)
