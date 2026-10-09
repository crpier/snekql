"""MariaDB identifier quoting helpers."""


def quote_identifier(identifier: str) -> str:
    """Quote a MariaDB identifier with backtick escaping."""

    return "`" + identifier.replace("`", "``") + "`"
