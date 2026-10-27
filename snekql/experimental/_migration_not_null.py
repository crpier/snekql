"""Explicit NOT NULL clause binding, separate from effective key nullability."""

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

_CONSTRAINT_PREFIX_TOKENS = 2
_CONFLICT_TOKENS = 3
_POLICIES = frozenset({"rollback", "abort", "fail", "ignore", "replace"})


def _not_null(definition: str, backend: Backend) -> tuple[str | None, str] | None:
    """Locate a top-level NOT NULL, excluding quoted/default/nested mentions."""
    stream = tokens(definition, mysql=backend == "mariadb")
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if (
            not depth
            and (token.kind, ascii_lower(token.value)) == ("word", "not")
            and index + 1 < len(stream)
            and (stream[index + 1].kind, ascii_lower(stream[index + 1].value))
            == ("word", "null")
        ):
            positions.append(index)
    if len(positions) > 1:
        msg = "multiple NOT NULL clauses require an explicit adapter"
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
            msg = (
                "unsupported NOT NULL clause constraint name; explicit adapter required"
            )
            raise PackageError(msg)
        if backend != "sqlite":
            msg = "named native NOT NULL clause requires an explicit adapter"
            raise PackageError(msg)
        name = label.value
    return name, _policy(stream[position + 2 :], backend)


def _policy(stream: tuple[Token, ...], backend: Backend) -> str:
    """Consume only this clause's conflict policy, not one on a following constraint."""
    words = tuple(ascii_lower(t.value) if t.kind == "word" else None for t in stream)
    index = 0
    policy = "abort" if backend == "sqlite" else "native"
    if words[:2] == ("on", "conflict"):
        if (
            backend != "sqlite"
            or len(words) < _CONFLICT_TOKENS
            or words[2] not in _POLICIES
        ):
            msg = (
                "unsupported NOT NULL clause conflict policy; explicit adapter required"
            )
            raise PackageError(msg)
        policy = str(words[2])
        index = _CONFLICT_TOKENS
    boundaries = {
        "constraint",
        "primary",
        "unique",
        "check",
        "default",
        "collate",
        "references",
        "generated",
        "as",
        "null",
    }
    if backend == "mariadb":
        boundaries |= {"auto_increment", "comment", "visible", "invisible"}
        if words[index : index + 2] == ("on", "update"):
            return policy
    if index < len(words) and words[index] not in boundaries:
        msg = "unsupported NOT NULL clause suffix; explicit adapter required"
        raise PackageError(msg)
    return policy


def validate_column_not_null(column: ColumnState, backend: Backend) -> None:
    """Admit standalone operation definitions independently of final ownership."""
    try:
        _not_null(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify NOT NULL clause: {error}"
        raise PackageError(msg) from error


def validate_not_null_claims(table: TableState, backend: Backend) -> None:
    """Compare managed explicit clauses, not implicit key requiredness or extra fields."""
    mysql = backend == "mariadb"
    try:
        definitions = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            if _not_null(column.definition, backend) != _not_null(
                definitions[ascii_lower(column.name)], backend
            ):
                msg = f"NOT NULL clause differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify NOT NULL clause: {error}"
        raise PackageError(msg) from error
