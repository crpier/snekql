"""MariaDB identifier quoting helpers."""

from __future__ import annotations


def quote_identifier(identifier: str) -> str:
    """Quote a MariaDB identifier with backtick escaping."""

    return "`" + identifier.replace("`", "``") + "`"
