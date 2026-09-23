"""Backend witnesses cannot be widened to accept a mixed union."""

from specialized import MariaDB, SQLite, integer, project, text

left = project(SQLite, event_id=integer(), title=text())
right = project(MariaDB, event_id=integer(), title=text())
left.union_all(right)
