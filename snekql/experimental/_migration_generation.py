"""Bounded generated kind/expression construction binding, never SQL equivalence."""

from snekql.errors import SchemaError
from snekql.experimental._migration_default_claims import _without_outer_parentheses
from snekql.experimental._migration_mariadb import mariadb_declared_generation
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


def _generation(
    definition: str, backend: Backend, *, columns: frozenset[str] = frozenset()
) -> tuple[str, str | None, tuple[tuple[str, str], ...]] | None:
    """Read top-level generated expression tokens separately from column/type names."""
    native_kind = (
        mariadb_declared_generation(definition) if backend == "mariadb" else None
    )
    stream = tokens(definition, mysql=backend == "mariadb")
    depth = 0
    positions: list[int] = []
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == ("word", "as"):
            positions.append(index)
    if not positions:
        if backend == "sqlite" and _top_markers(stream):
            msg = (
                "unsupported construction generation clause; explicit adapter required"
            )
            raise PackageError(msg)
        return None
    if len(positions) != 1:
        msg = "multiple construction generation clauses require an explicit adapter"
        raise PackageError(msg)
    start = positions[0] + 1
    if start >= len(stream) or (stream[start].kind, stream[start].value) != (
        "punct",
        "(",
    ):
        msg = (
            "unsupported construction generation expression; explicit adapter required"
        )
        raise PackageError(msg)
    end = _expression_end(stream, start)
    if backend == "mariadb":
        _native_identifier_quotes(definition, stream[start + 1 : end - 1])
    kind = native_kind or _sqlite_kind(stream, positions[0], end)
    return (
        kind,
        _label(stream, positions[0]),
        _scalar(stream[start + 1 : end - 1], backend, columns),
    )


def _native_identifier_quotes(definition: str, stream: tuple[Token, ...]) -> None:
    """Require backtick references rather than infer ANSI_QUOTES/MSSQL execution modes."""
    if any(
        token.kind == "identifier" and definition[token.start] != "`"
        for token in stream
    ):
        msg = "unsupported construction generation expression identifier quote; explicit adapter required"
        raise PackageError(msg)


_GENERATION_MARKERS = frozenset(
    {"generated", "always", "virtual", "stored", "persistent"}
)
_GENERATION_BOUNDARIES = frozenset(
    {
        "constraint",
        "not",
        "null",
        "unique",
        "check",
        "collate",
        "references",
        "primary",
        "default",
    }
)


def _top_markers(stream: tuple[Token, ...]) -> tuple[tuple[int, str], ...]:
    """Find only top-level generation decorations, not expression/literal mentions."""
    depth = 0
    markers: list[tuple[int, str]] = []
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if (
            not depth
            and token.kind == "word"
            and ascii_lower(token.value) in _GENERATION_MARKERS
        ):
            markers.append((index, ascii_lower(token.value)))
    return tuple(markers)


def _sqlite_kind(stream: tuple[Token, ...], position: int, end: int) -> str:
    """Admit optional GENERATED ALWAYS and one physical mode, not stray suffixes."""
    expected: list[tuple[int, str]] = []
    if tuple(
        (t.kind, ascii_lower(t.value)) for t in stream[position - 2 : position]
    ) == (("word", "generated"), ("word", "always")):
        expected.extend(((position - 2, "generated"), (position - 1, "always")))
    kind = "virtual"
    if (
        end < len(stream)
        and stream[end].kind == "word"
        and ascii_lower(stream[end].value) in {"virtual", "stored"}
    ):
        kind = ascii_lower(stream[end].value)
        expected.append((end, kind))
        end += 1
    if _top_markers(stream) != tuple(expected) or (
        end < len(stream)
        and (
            stream[end].kind != "word"
            or ascii_lower(stream[end].value) not in _GENERATION_BOUNDARIES
        )
    ):
        msg = "unsupported construction generation prefix/mode/suffix; explicit adapter required"
        raise PackageError(msg)
    return kind


_CONSTRAINT_PREFIX_TOKENS = 2


def _label(stream: tuple[Token, ...], position: int) -> str | None:
    """Bind a SQLite generated clause's own label, not a following constraint's."""
    if tuple(
        (t.kind, ascii_lower(t.value)) for t in stream[position - 2 : position]
    ) == (("word", "generated"), ("word", "always")):
        position -= 2
    if position < _CONSTRAINT_PREFIX_TOKENS or (
        stream[position - 2].kind,
        ascii_lower(stream[position - 2].value),
    ) != ("word", "constraint"):
        return None
    label = stream[position - 1]
    if label.kind not in {"word", "identifier"}:
        msg = "unsupported construction generation constraint name; explicit adapter required"
        raise PackageError(msg)
    return label.value


def _expression_end(stream: tuple[Token, ...], start: int) -> int:
    """Find the closing delimiter iteratively, preserving nested expression roles."""
    depth = 1
    end = start + 1
    while end < len(stream) and depth:
        token = stream[end]
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        end += 1
    if depth:
        msg = (
            "unterminated construction generation expression; explicit adapter required"
        )
        raise PackageError(msg)
    return end


_EXPRESSION_TOKENS = 64
_CAST_TOKENS = 6
_INTEGER_DIGITS = 19
_ADDITION_TOKENS = 3


def _integer(stream: tuple[Token, ...]) -> tuple[tuple[str, str], ...] | None:
    """Admit signed 64-bit decimal constants without unbounded integer conversion."""
    sign = 1
    if stream and (stream[0].kind, stream[0].value) in {("punct", "+"), ("punct", "-")}:
        sign = -1 if stream[0].value == "-" else 1
        stream = stream[1:]
    if len(stream) != 1 or stream[0].kind != "word":
        return None
    text = stream[0].value
    if not text.isascii() or not text.isdecimal() or len(text) > _INTEGER_DIGITS:
        return None
    value = sign * int(text)
    return (("integer", str(value)),) if -(2**63) <= value < 2**63 else None


def _scalar(
    stream: tuple[Token, ...], backend: Backend, columns: frozenset[str]
) -> tuple[tuple[str, str], ...]:
    """Admit only finite scalar terms, never evaluate SQL/functions to claim equivalence."""
    if len(stream) > _EXPRESSION_TOKENS:
        msg = "construction generation expression exceeds the 64-token limit"
        raise PackageError(msg)
    stream = _without_outer_parentheses(stream)
    if integer := _integer(stream):
        return integer
    if len(stream) == 1 and stream[0].kind == "string":
        return (("string", stream[0].value),)
    if len(stream) == 1 and (stream[0].kind, ascii_lower(stream[0].value)) == (
        "word",
        "null",
    ):
        return (("null", ""),)
    words = tuple((t.kind, ascii_lower(t.value)) for t in stream)
    if (
        backend == "mariadb"
        and len(stream) >= _CAST_TOKENS
        and words[:2] == (("word", "cast"), ("punct", "("))
        and words[-3:] == (("word", "as"), ("word", "signed"), ("punct", ")"))
        and (integer := _integer(stream[2:-3]))
    ):
        return (("cast", "signed"), *integer)
    if member := _member_expression(stream, columns):
        return member
    msg = "unsupported construction generation expression; explicit adapter required"
    raise PackageError(msg)


def _member_expression(
    stream: tuple[Token, ...], columns: frozenset[str]
) -> tuple[tuple[str, str], ...] | None:
    """Admit a full declared column reference, optionally plus one integer literal."""
    if (
        not stream
        or stream[0].kind != "identifier"
        or ascii_lower(stream[0].value) not in columns
    ):
        return None
    member = (("column", ascii_lower(stream[0].value)),)
    if len(stream) == 1:
        return member
    if (
        len(stream) >= _ADDITION_TOKENS
        and (stream[1].kind, stream[1].value) == ("punct", "+")
        and (integer := _integer(stream[2:]))
    ):
        return (*member, ("operator", "+"), *integer)
    return None


def validate_column_generation(column: ColumnState, backend: Backend) -> None:
    """Admit standalone terms independently of final ownership/operation permission."""
    try:
        _generation(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify construction generation: {error}"
        raise PackageError(msg) from error


def validate_generation_claims(table: TableState, backend: Backend) -> None:
    """Bind only managed declarations; extra SQL generated fields do not create claims."""
    mysql = backend == "mariadb"
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        members = frozenset(declarations)
        for column in table.columns:
            if _generation(column.definition, backend, columns=members) != _generation(
                declarations[ascii_lower(column.name)],
                backend,
                columns=members,
            ):
                msg = f"construction generation differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction generation: {error}"
        raise PackageError(msg) from error
