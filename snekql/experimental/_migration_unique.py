"""Bounded inline UNIQUE binding, independent of table keys and index ownership."""

from snekql.errors import SchemaError
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


def _inline_unique(definition: str, backend: Backend) -> tuple[str | None, str] | None:
    """Find a top-level clause, not a literal, identifier or expression mention."""
    depth = 0
    positions: list[int] = []
    stream = tokens(definition, mysql=backend == "mariadb")
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == ("word", "unique"):
            positions.append(index)
    if len(positions) > 1:
        msg = "multiple inline UNIQUE clauses require an explicit adapter"
        raise PackageError(msg)
    if not positions:
        return None
    position = positions[0]
    name = None
    if position >= _CONSTRAINT_PREFIX_TOKENS and (
        stream[position - 2].kind,
        ascii_lower(stream[position - 2].value),
    ) == ("word", "constraint"):
        label = stream[position - 1]
        if label.kind not in {"word", "identifier"}:
            msg = "unsupported inline UNIQUE constraint name; explicit adapter required"
            raise PackageError(msg)
        if backend != "sqlite":
            msg = "named native inline UNIQUE requires an explicit adapter"
            raise PackageError(msg)
        name = label.value
    return name, _unique_policy(stream[position + 1 :], backend)


_CONSTRAINT_PREFIX_TOKENS = 2
_CONFLICT_TOKENS = 3
_CONFLICT_POLICIES = frozenset({"rollback", "abort", "fail", "ignore", "replace"})


def _unique_policy(stream: tuple[Token, ...], backend: Backend) -> str:
    """Consume the UNIQUE clause's own policy, not another constraint's ON CONFLICT."""
    words = tuple(ascii_lower(t.value) if t.kind == "word" else None for t in stream)
    index = int(backend == "mariadb" and words[:1] == ("key",))
    policy = "abort" if backend == "sqlite" else "native"
    if words[index : index + 2] == ("on", "conflict"):
        if (
            backend != "sqlite"
            or len(words) < index + _CONFLICT_TOKENS
            or words[index + 2] not in _CONFLICT_POLICIES
        ):
            msg = "unsupported inline UNIQUE conflict policy; explicit adapter required"
            raise PackageError(msg)
        policy = str(words[index + 2])
        index += _CONFLICT_TOKENS
    boundaries = {
        "constraint",
        "primary",
        "not",
        "null",
        "check",
        "default",
        "collate",
        "references",
        "generated",
        "as",
    }
    if backend == "mariadb":
        boundaries |= {"auto_increment", "comment", "visible", "invisible"}
        if words[index : index + 2] == ("on", "update"):
            return policy
    if index < len(words) and words[index] not in boundaries:
        msg = "unsupported inline UNIQUE suffix; explicit adapter required"
        raise PackageError(msg)
    return policy


def validate_column_unique(column: ColumnState, backend: Backend) -> None:
    """Admit standalone ADD/default payloads without manufacturing index authority."""
    try:
        _inline_unique(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify inline UNIQUE: {error}"
        raise PackageError(msg) from error


def validate_unique_claims(table: TableState, backend: Backend) -> None:
    """Bind each managed UNIQUE claim including absence; do not claim extra columns."""
    mysql = backend == "mariadb"
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            if _inline_unique(column.definition, backend) != _inline_unique(
                declarations[ascii_lower(column.name)], backend
            ):
                msg = f"inline UNIQUE differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify inline UNIQUE: {error}"
        raise PackageError(msg) from error
