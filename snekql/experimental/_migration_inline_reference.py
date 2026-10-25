"""Bounded SQLite inline REFERENCES binding, not parent adoption or FK compatibility."""

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


def _reference(definition: str) -> tuple[str, str, str, str, str | None] | None:
    """Read one top-level REFERENCES role, never names/literals/nested expressions."""
    stream = tokens(definition)
    depth = 0
    positions: list[int] = []
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == (
            "word",
            "references",
        ):
            positions.append(index)
    if not positions:
        return None
    if len(positions) != 1:
        msg = "multiple construction inline REFERENCES require an explicit adapter"
        raise PackageError(msg)
    return (*_clause(stream[positions[0] + 1 :]), _label(stream, positions[0]))


_LABEL_PREFIX = 2


def _label(stream: tuple[Token, ...], position: int) -> str | None:
    """Bind this REFERENCES label, never one on a later constraint."""
    if position < _LABEL_PREFIX or (
        stream[position - 2].kind,
        ascii_lower(stream[position - 2].value),
    ) != ("word", "constraint"):
        return None
    label = stream[position - 1]
    if label.kind not in {"word", "identifier"} or not label.value:
        msg = (
            "unsupported construction inline REFERENCES name; explicit adapter required"
        )
        raise PackageError(msg)
    return label.value


_TARGET_TOKENS = 4
_ACTION_TOKENS = 3
_BOUNDARIES = frozenset(
    {
        "constraint",
        "primary",
        "not",
        "null",
        "unique",
        "check",
        "default",
        "collate",
        "generated",
        "as",
    }
)


def _clause(stream: tuple[Token, ...]) -> tuple[str, str, str, str]:
    """Require explicit unqualified target/member and bounded immediate actions."""
    if (
        len(stream) < _TARGET_TOKENS
        or stream[0].kind not in {"word", "identifier"}
        or stream[2].kind not in {"word", "identifier"}
        or (stream[1].kind, stream[1].value) != ("punct", "(")
        or (stream[3].kind, stream[3].value) != ("punct", ")")
    ):
        msg = "unsupported construction inline REFERENCES target/member; explicit adapter required"
        raise PackageError(msg)
    actions: dict[str, str] = {}
    words = tuple(ascii_lower(t.value) if t.kind == "word" else None for t in stream)
    position = _TARGET_TOKENS
    while position < len(stream) and words[position] == "on":
        action, size = _action(words[position:])
        kind = str(words[position + 1])
        if kind in actions:
            msg = "unsupported construction inline REFERENCES duplicate action; explicit adapter required"
            raise PackageError(msg)
        actions[kind] = action
        position += size
    if position < len(stream) and (
        words[position] not in _BOUNDARIES
        or (
            words[position] == "not" and words[position + 1 : position + 2] != ("null",)
        )
    ):
        msg = "unsupported construction inline REFERENCES suffix; explicit adapter required"
        raise PackageError(msg)
    return (
        ascii_lower(stream[0].value),
        ascii_lower(stream[2].value),
        actions.get("delete", "no action"),
        actions.get("update", "no action"),
    )


def _action(words: tuple[str | None, ...]) -> tuple[str, int]:
    """Keep SQLite NO ACTION distinct from RESTRICT; defer SET/timing/MATCH language."""
    if len(words) >= _ACTION_TOKENS and words[1] in {"delete", "update"}:
        if words[2] in {"cascade", "restrict"}:
            return str(words[2]), _ACTION_TOKENS
        if words[2:4] == ("no", "action"):
            return "no action", _ACTION_TOKENS + 1
    msg = "unsupported construction inline REFERENCES action; explicit adapter required"
    raise PackageError(msg)


def validate_column_inline_reference(column: ColumnState, backend: Backend) -> None:
    """Admit standalone reference terms independently of final ownership/operation permission."""
    if backend == "sqlite":
        _reference(column.definition)


def validate_inline_reference_claims(table: TableState, backend: Backend) -> None:
    """Bind only managed SQLite references; extra SQL fields grant no parent/child ownership."""
    if backend != "sqlite":
        return
    try:
        declarations = {
            ascii_lower(name): part
            for part in split_table(table.sql)[1]
            if tokens(part) and (name := column_name(part)) is not None
        }
        for column in table.columns:
            if _reference(column.definition) != _reference(
                declarations[ascii_lower(column.name)]
            ):
                msg = f"construction inline REFERENCES differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify construction inline REFERENCES: {error}"
        raise PackageError(msg) from error
