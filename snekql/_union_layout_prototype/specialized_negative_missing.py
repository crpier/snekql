"""All declared output fields are required."""

from specialized import SQLite, integer, project

project(SQLite, event_id=integer())
