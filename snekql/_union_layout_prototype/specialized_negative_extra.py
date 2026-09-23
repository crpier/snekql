"""Undeclared output fields cannot enter a named result."""

from specialized import SQLite, integer, project, text

project(SQLite, event_id=integer(), title=text(), extra=text())
