"""A text expression cannot supply an integer field."""

from specialized import SQLite, project, text

project(SQLite, event_id=text(), title=text())
