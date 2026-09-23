"""Must reject incompatible logical domains at composition, not fetching."""

from selector import Fields, Query, integer, text

left = Query(Fields(event_id=integer(), title=text()))
wrong = Query(Fields(event_id=text(), title=text()))
left.union_all(wrong)
