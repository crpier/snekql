"""Bounded SQLite inline CHECK construction identity, not arbitrary SQL equivalence."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import _bounded_check_expression
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

type _Check = tuple[str | None, tuple[tuple[str, str], ...]]
_LABEL_PREFIX_TOKENS = 2


def _label(stream: tuple[Token, ...], position: int) -> str | None:
    """Read only this CHECK's optional label, not a following constraint's."""
    if position < _LABEL_PREFIX_TOKENS or (
        stream[position - 2].kind,
        ascii_lower(stream[position - 2].value),
    ) != ("word", "constraint"):
        return None
    label = stream[position - 1]
    if label.kind not in {"word", "identifier"} or not label.value:
        msg = "unsupported construction inline CHECK constraint name; explicit adapter required"
        raise PackageError(msg)
    return label.value


def _checks(definition: str, columns: frozenset[str]) -> tuple[_Check, ...]:
    """Keep ordered inline CHECK bodies without promoting nested names/literals."""
    stream = tokens(definition)
    depth = 0
    result: list[_Check] = []
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == ("word", "check"):
            body, end = _body(stream, index + 1)
            _suffix(stream[end:])
            _expression(definition, body, columns)
            result.append(
                (
                    _label(stream, index),
                    tuple(
                        (
                            t.kind,
                            ascii_lower(t.value)
                            if t.kind in {"word", "identifier"}
                            else t.value,
                        )
                        for t in body
                    ),
                )
            )
    return tuple(result)


def _expression(
    definition: str, body: tuple[Token, ...], columns: frozenset[str]
) -> None:
    """Admit the existing finite CHECK grammar/resources, not its normalization as equivalence."""
    try:
        expression = _bounded_check_expression(definition, body)
    except PackageError as error:
        msg = f"unsupported construction inline CHECK expression; explicit adapter required: {error}"
        raise PackageError(msg) from error
    pending = [expression]
    while pending:
        node = pending.pop()
        if node.operator == "column" and (
            not isinstance(node.value, str) or ascii_lower(node.value) not in columns
        ):
            msg = "unsupported construction inline CHECK member; explicit adapter required"
            raise PackageError(msg)
        pending.extend(node.arguments)


_BOUNDARIES = frozenset(
    {
        "constraint",
        "primary",
        "unique",
        "not",
        "null",
        "check",
        "default",
        "collate",
        "references",
        "generated",
        "as",
    }
)


def _suffix(stream: tuple[Token, ...]) -> None:
    """Admit a following known column constraint, not an unknown CHECK policy/suffix."""
    if stream and (
        stream[0].kind != "word" or ascii_lower(stream[0].value) not in _BOUNDARIES
    ):
        msg = "unsupported construction inline CHECK suffix; explicit adapter required"
        raise PackageError(msg)


def _body(stream: tuple[Token, ...], start: int) -> tuple[tuple[Token, ...], int]:
    """Extract one balanced body iteratively, preserving suffix roles."""
    if start >= len(stream) or (stream[start].kind, stream[start].value) != (
        "punct",
        "(",
    ):
        msg = "unsupported construction inline CHECK body; explicit adapter required"
        raise PackageError(msg)
    depth = 1
    end = start + 1
    while end < len(stream) and depth:
        token = stream[end]
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        end += 1
    if depth:
        msg = "unsupported construction inline CHECK body; explicit adapter required"
        raise PackageError(msg)
    return stream[start + 1 : end - 1], end


def validate_column_inline_check(column: ColumnState, backend: Backend) -> None:
    """Admit standalone SQLite CHECK language independently of final ownership."""
    if backend == "sqlite":
        _checks(column.definition, frozenset({ascii_lower(column.name)}))


def validate_inline_check_claims(table: TableState, backend: Backend) -> None:
    """Bind only managed column CHECKs; extra SQL columns create no owned constraints."""
    if backend != "sqlite":
        return
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql)[1]
            if tokens(part) and (name := column_name(part)) is not None
        }
        members = frozenset(declarations)
        for column in table.columns:
            if _checks(column.definition, members) != _checks(
                declarations[ascii_lower(column.name)], members
            ):
                msg = f"construction inline CHECK differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction inline CHECK: {error}"
        raise PackageError(msg) from error
