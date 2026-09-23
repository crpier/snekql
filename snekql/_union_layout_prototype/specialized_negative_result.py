"""Different result schemas cannot be combined."""

from specialized import SQLite, integer, other_result, project, text

left = project(SQLite, event_id=integer(), title=text())
right = other_result(SQLite, event_id=integer())
left.union_all(right)
