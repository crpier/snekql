"""Bounded ordinary-column nullability claims, separate from primary-key semantics."""

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import (
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


def _declared_nullable(source: str, backend: Backend) -> bool | None:
    """Read top-level NULL clauses; inline primary keys retain their separate proof."""
    stream = tokens(source, mysql=backend == "mariadb")
    depth = 0
    flags: list[bool] = []
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if depth or token.kind != "word":
            continue
        word = ascii_lower(token.value)
        following = stream[index + 1] if index + 1 < len(stream) else None
        if (
            word == "primary"
            and following
            and (following.kind, ascii_lower(following.value)) == ("word", "key")
        ):
            return None
        if word != "null":
            continue
        previous = stream[index - 1]
        keyword = ascii_lower(previous.value) if previous.kind == "word" else None
        if keyword != "default":
            flags.append(keyword != "not")
    if len(flags) > 1:
        msg = "ordinary column nullability has multiple clauses; explicit adapter required"
        raise PackageError(msg)
    return flags[0] if flags else True


def _table_key_members(parts: tuple[str, ...], backend: Backend) -> set[str]:
    """Exclude potential table-key members, without certifying their key semantics."""
    members: set[str] = set()
    for part in parts:
        stream = tokens(part, mysql=backend == "mariadb")
        words = tuple((t.kind, ascii_lower(t.value)) for t in stream)
        start = 2 if words and words[0] == ("word", "constraint") else 0
        if words[start : start + 2] != (("word", "primary"), ("word", "key")):
            continue
        depth = 0
        for i, token in enumerate(stream[start + 2 :], start=start + 2):
            if token.kind == "punct":
                depth += (token.value == "(") - (token.value == ")")
            elif depth == 1 and stream[i - 1].value in {"(", ","}:
                members.add(ascii_lower(token.value))
    return members


def validate_column_nullability(column: ColumnState, backend: Backend) -> None:
    """Bind standalone ADD/default operation flags before their table is projected."""
    try:
        nullable = _declared_nullable(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify ordinary column nullability: {error}"
        raise PackageError(msg) from error
    if nullable is not None and nullable != column.nullable:
        msg = f"ordinary column nullability differs for {column.name!r}"
        raise PackageError(msg)


def validate_nullability_claims(table: TableState, backend: Backend) -> None:
    """Refuse ordinary flag/definition/construction contradictions; keys stay separate."""
    mysql = backend == "mariadb"
    try:
        parts = split_table(table.sql, mysql=mysql)[1]
        keys = _table_key_members(parts, backend)
        declarations = {
            ascii_lower(name): part
            for part in parts
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            if ascii_lower(column.name) in keys:
                continue
            flags = (
                _declared_nullable(column.definition, backend),
                _declared_nullable(declarations[ascii_lower(column.name)], backend),
            )
            if None not in flags and any(flag != column.nullable for flag in flags):
                msg = f"ordinary column nullability differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify ordinary column nullability: {error}"
        raise PackageError(msg) from error
