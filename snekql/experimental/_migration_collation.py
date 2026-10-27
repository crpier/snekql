"""Bounded column collation agreement, not expression or session equivalence."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import mariadb_declared_collation
from snekql.experimental._migration_sql import (
    Token,
    ascii_lower,
    column_name,
    split_table,
    tokens,
)
from snekql.experimental.migrations import (
    Backend,
    ColumnState,
    PackageError,
    TableState,
)

_CONSTRAINT_PREFIX_TOKENS = 2


def _collation(definition: str, backend: Backend) -> tuple[str | None, str | None]:
    """Read one SQLite built-in column collation, not quoted/nested expression mentions."""
    if backend == "mariadb":
        return None, mariadb_declared_collation(definition)
    stream = tokens(definition)
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == ("word", "collate"):
            positions.append(index)
    if len(positions) > 1:
        msg = "multiple construction collation clauses require an explicit adapter"
        raise PackageError(msg)
    if not positions:
        return None, "binary"
    position = positions[0]
    if (
        position + 1 >= len(stream)
        or stream[position + 1].kind not in {"word", "identifier"}
        or ascii_lower(stream[position + 1].value) not in {"binary", "nocase", "rtrim"}
    ):
        msg = "unsupported SQLite construction collation; explicit adapter required"
        raise PackageError(msg)
    boundaries = {
        "constraint",
        "primary",
        "not",
        "null",
        "unique",
        "check",
        "default",
        "references",
        "generated",
        "as",
    }
    if position + 2 < len(stream) and (
        stream[position + 2].kind != "word"
        or ascii_lower(stream[position + 2].value) not in boundaries
    ):
        msg = "unsupported construction collation suffix; explicit adapter required"
        raise PackageError(msg)
    return _constraint_name(stream, position), ascii_lower(stream[position + 1].value)


def _constraint_name(stream: tuple[Token, ...], position: int) -> str | None:
    """Read only the COLLATE clause's own optional SQLite label."""
    if position < _CONSTRAINT_PREFIX_TOKENS or (
        stream[position - 2].kind,
        ascii_lower(stream[position - 2].value),
    ) != ("word", "constraint"):
        return None
    label = stream[position - 1]
    if label.kind not in {"word", "identifier"}:
        msg = "unsupported construction collation constraint name; explicit adapter required"
        raise PackageError(msg)
    return label.value


def validate_column_collation(column: ColumnState, backend: Backend) -> None:
    """Admit standalone terms without inferring final ownership or operation permission."""
    try:
        _collation(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify construction collation: {error}"
        raise PackageError(msg) from error


def validate_collation_claims(table: TableState, backend: Backend) -> None:
    """Compare managed declaration facts; extra SQL fields do not manufacture authority."""
    mysql = backend == "mariadb"
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            if _collation(column.definition, backend) != _collation(
                declarations[ascii_lower(column.name)], backend
            ):
                msg = (
                    f"construction collation differs for {table.name!r}.{column.name!r}"
                )
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction collation: {error}"
        raise PackageError(msg) from error
