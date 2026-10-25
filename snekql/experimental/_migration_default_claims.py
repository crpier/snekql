"""Bounded default definition/construction agreement, never SQL evaluation."""

from snekql._check_catalog import parse_default_literal
from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import (
    mariadb_declared_default,
    mariadb_declared_null_default,
)
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

_SQLITE_CLAUSES = frozenset(
    {
        "constraint",
        "primary",
        "not",
        "null",
        "unique",
        "check",
        "references",
        "collate",
        "generated",
        "as",
    }
)
_SQLITE_CLOCK = "strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z'"


def _sqlite_term(definition: str) -> str | None:
    """Separate one whole term; do not mistake a scalar prefix for an expression."""
    stream = tokens(definition)
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if depth == 0 and (token.kind, ascii_lower(token.value)) == ("word", "default"):
            positions.append(index)
    if not positions:
        return None
    if len(positions) != 1:
        msg = "multiple DEFAULT clauses require an explicit adapter"
        raise PackageError(msg)
    start = positions[0] + 1
    if start >= len(stream):
        msg = "empty DEFAULT clause"
        raise PackageError(msg)
    depth = 0
    end = len(definition)
    for index in range(start, len(stream)):
        token = stream[index]
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if (
            index > start
            and depth == 0
            and token.kind == "word"
            and ascii_lower(token.value) in _SQLITE_CLAUSES
        ):
            end = token.start
            break
    return definition[stream[start].start : end].strip()


def _without_outer_parentheses(stream: tuple[Token, ...]) -> tuple[Token, ...]:
    """Strip cosmetic wrappers in linear work, not repeated full-stream scans."""
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for index, token in enumerate(stream):
        if (token.kind, token.value) == ("punct", "("):
            stack.append(index)
        elif (token.kind, token.value) == ("punct", ")"):
            if not stack:
                return stream
            pairs[stack.pop()] = index
    if stack:
        return stream
    start, end = 0, len(stream)
    while start < end and pairs.get(start) == end - 1:
        start += 1
        end -= 1
    return stream[start:end]


def _sqlite_default(definition: str) -> tuple[str, object] | None:
    term = _sqlite_term(definition)
    if term is None:
        return None
    literal = parse_default_literal(term, mariadb=False)
    if literal is not None:
        return "literal", (type(literal.value).__name__, literal.value)
    stream = _without_outer_parentheses(tokens(term))
    signature = tuple(
        (t.kind, ascii_lower(t.value) if t.kind == "word" else t.value) for t in stream
    )
    clock = tuple(
        (t.kind, ascii_lower(t.value) if t.kind == "word" else t.value)
        for t in tokens(_SQLITE_CLOCK)
    )
    if ascii_lower(tokens(definition)[1].value) == "text" and signature == clock:
        return "clock", clock
    msg = "unsupported SQLite DEFAULT expression; explicit adapter required"
    raise PackageError(msg)


def _default(
    column: ColumnState, definition: str, backend: Backend
) -> tuple[str, object] | None:
    if backend == "sqlite":
        return _sqlite_default(definition)
    if mariadb_declared_null_default(definition) and not column.nullable:
        msg = "MariaDB DEFAULT NULL requires a nullable recorded column; explicit adapter required"
        raise PackageError(msg)
    result = mariadb_declared_default(definition)
    # Native nullable omission and explicit NULL share the existing effective-NULL
    # contract. This does not claim that their declaration spelling is identical.
    return ("literal", None) if result is None and column.nullable else result


def validate_column_default(column: ColumnState, backend: Backend) -> None:
    """Admit standalone ADD/default terms even if later relinquished."""
    try:
        _default(column, column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify construction default: {error}"
        raise PackageError(msg) from error


def validate_default_claims(table: TableState, backend: Backend) -> None:
    """Bind positive default claims without expanding the managed column set."""
    mysql = backend == "mariadb"
    try:
        definitions = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            actual = definitions[ascii_lower(column.name)]
            if _default(column, column.definition, backend) != _default(
                column, actual, backend
            ):
                msg = f"construction default differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction default: {error}"
        raise PackageError(msg) from error
