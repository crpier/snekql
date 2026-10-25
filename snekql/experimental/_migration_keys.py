"""Bounded inline key binding and table-key membership, not full key semantics proof."""

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

_CONFLICT_TOKENS = 3


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


def table_primary_key_members(
    parts: tuple[str, ...], backend: Backend
) -> tuple[str, ...]:
    """Read one bounded full-column table key for membership, not index equivalence."""
    keys: list[tuple[str, ...]] = []
    for part in parts:
        stream = tokens(part, mysql=backend == "mariadb")
        words = tuple((t.kind, ascii_lower(t.value)) for t in stream)
        start = 0
        if words[:1] == (("word", "constraint"),):
            start = (
                1
                if backend == "mariadb" and words[1:2] == (("word", "primary"),)
                else 2
            )
        if words[start : start + 1] != (("word", "primary"),):
            continue
        if words[start : start + 3] != (
            ("word", "primary"),
            ("word", "key"),
            ("punct", "("),
        ):
            msg = "unsupported primary-key membership; explicit adapter required"
            raise PackageError(msg)
        keys.append(_full_key_members(stream[start + 3 :], backend))
    if len(keys) > 1:
        msg = "multiple primary-key declarations require an explicit adapter"
        raise PackageError(msg)
    return keys[0] if keys else ()


def _full_key_members(stream: tuple[Token, ...], backend: Backend) -> tuple[str, ...]:
    """Consume full member identifiers plus bounded direction/conflict decoration."""
    members: list[str] = []
    index = 0
    while index < len(stream):
        token = stream[index]
        if token.kind not in {"word", "identifier"} or (
            token.kind == "word"
            and token.value[0].isascii()
            and token.value[0].isdigit()
        ):
            msg = "unsupported primary-key member; explicit adapter required"
            raise PackageError(msg)
        members.append(ascii_lower(token.value))
        index += 1
        if (
            index < len(stream)
            and stream[index].kind == "word"
            and ascii_lower(stream[index].value)
            in ({"asc"} if backend == "mariadb" else {"asc", "desc"})
        ):
            index += 1
        if index < len(stream) and (stream[index].kind, stream[index].value) == (
            "punct",
            ")",
        ):
            index += 1
            break
        if index >= len(stream) or (stream[index].kind, stream[index].value) != (
            "punct",
            ",",
        ):
            msg = "unsupported primary-key member suffix; explicit adapter required"
            raise PackageError(msg)
        index += 1
    else:
        msg = "unterminated primary-key membership; explicit adapter required"
        raise PackageError(msg)
    tail = tuple((t.kind, ascii_lower(t.value)) for t in stream[index:])
    if tail and not (
        backend == "sqlite"
        and len(tail) == _CONFLICT_TOKENS
        and tail[:2] == (("word", "on"), ("word", "conflict"))
        and tail[2][0] == "word"
        and tail[2][1] in {"rollback", "abort", "fail", "ignore", "replace"}
    ):
        msg = "unsupported primary-key membership policy; explicit adapter required"
        raise PackageError(msg)
    if len(set(members)) != len(members):
        msg = "ambiguous primary-key members require an explicit adapter"
        raise PackageError(msg)
    return tuple(members)
