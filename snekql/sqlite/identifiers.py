"""SQLite SQL identifier helpers."""

from __future__ import annotations


def quote_identifier(identifier: str) -> str:
    """Quote a SQLite identifier with double-quote escaping.

    >>> quote_identifier('user')
    '"user"'
    >>> quote_identifier('weird"name')
    '"weird""name"'
    """

    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'
