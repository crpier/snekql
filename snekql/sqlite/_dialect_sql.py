"""Shared SQLite dialect SQL fragments."""

from __future__ import annotations

# Server-side ISO-8601 UTC timestamp, shared by the CurrentTimestamp DDL default,
# the migration-history applied_at default, and update-time server expressions so
# every server clock value uses one identical text format.
CURRENT_TIMESTAMP_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
