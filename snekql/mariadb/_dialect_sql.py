"""Shared MariaDB dialect SQL fragments."""

from __future__ import annotations

# Server-side timestamp with millisecond precision, shared by the CurrentTimestamp
# DDL default and update-time server expressions so both reference one fragment.
CURRENT_TIMESTAMP_SQL = "CURRENT_TIMESTAMP(3)"
