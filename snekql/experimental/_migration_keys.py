"""Bounded inline key claim binding, not table-key or rowid semantics proof."""

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


def _inline_key(definition: str, backend: Backend) -> tuple[str, str, bool] | None:
    """Locate one top-level key, excluding identifier/literal/expression mentions."""
    stream = tokens(definition, mysql=backend == "mariadb")
    positions: list[int] = []
    depth = 0
    for index, token in enumerate(stream[1:], start=1):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if depth == 0 and (token.kind, ascii_lower(token.value)) == ("word", "primary"):
            if index + 1 >= len(stream) or (
                stream[index + 1].kind,
                ascii_lower(stream[index + 1].value),
            ) != ("word", "key"):
                msg = "unsupported inline primary key clause; explicit adapter required"
                raise PackageError(msg)
            positions.append(index)
    if len(positions) > 1:
        msg = "multiple inline primary key clauses require an explicit adapter"
        raise PackageError(msg)
    return _key_policy(stream[positions[0] + 2 :], backend) if positions else None


def _key_policy(stream: tuple[Token, ...], backend: Backend) -> tuple[str, str, bool]:
    """Read the inline key's own policy, not following NOT NULL/UNIQUE policies."""
    words = tuple(ascii_lower(t.value) if t.kind == "word" else None for t in stream)
    index = 0
    direction, conflict, identity = "asc", "abort", False
    if words[:1] in (("asc",), ("desc",)):
        if backend != "sqlite":
            msg = "unsupported native inline primary key direction; explicit adapter required"
            raise PackageError(msg)
        direction = str(words[0])
        index += 1
    if words[index : index + 2] == ("on", "conflict"):
        if (
            backend != "sqlite"
            or index + 2 >= len(words)
            or words[index + 2]
            not in {"rollback", "abort", "fail", "ignore", "replace"}
        ):
            msg = "unsupported inline primary key conflict policy; explicit adapter required"
            raise PackageError(msg)
        conflict = str(words[index + 2])
        index += 3
    if words[index : index + 1] == ("autoincrement",) and backend == "sqlite":
        identity = True
        index += 1
    boundaries = {
        "constraint",
        "not",
        "null",
        "unique",
        "check",
        "default",
        "collate",
        "references",
        "generated",
        "as",
    }
    if backend == "mariadb":
        boundaries |= {"auto_increment", "comment", "invisible", "visible"}
        if words[index : index + 2] == ("on", "update"):
            return direction, conflict, identity
    if index < len(words) and words[index] not in boundaries:
        msg = "unsupported inline primary key suffix; explicit adapter required"
        raise PackageError(msg)
    return direction, conflict, identity


def validate_column_inline_key(column: ColumnState, backend: Backend) -> None:
    """Admit standalone operation definitions without inferring table key semantics."""
    try:
        _inline_key(column.definition, backend)
    except SchemaError as error:
        msg = f"cannot verify inline primary key: {error}"
        raise PackageError(msg) from error


def validate_inline_key_claims(table: TableState, backend: Backend) -> None:
    """Compare managed inline claims only; extra SQL columns do not manufacture claims."""
    mysql = backend == "mariadb"
    try:
        definitions = {
            ascii_lower(name): part
            for part in split_table(table.sql, mysql=mysql)[1]
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        for column in table.columns:
            if _inline_key(column.definition, backend) != _inline_key(
                definitions[ascii_lower(column.name)], backend
            ):
                msg = f"inline primary key differs for {table.name!r}.{column.name!r}"
                raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify inline primary key: {error}"
        raise PackageError(msg) from error
