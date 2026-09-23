"""A nullable combined result cannot be consumed as a required integer."""

from specialized import ID, Expr, SQLite, integer, optional_integer, project, text

left = project(SQLite, event_id=integer(), title=text())
right = project(SQLite, event_id=optional_integer(), title=text())
required: Expr[int] = left.union_all(right).column(ID)
