"""Bounded declaration/key-implied nullability, not a general constraint solver."""

from snekql.errors import SchemaError
from snekql.experimental._migration_keys import _inline_key, table_primary_key_members
from snekql.experimental._migration_sql import (
    ascii_lower,
    column_name,
    split_table,
    tokens,
)
from snekql.experimental._migration_storage import _sqlite_storage
from snekql.experimental.migrations import (
    Backend,
    ColumnState,
    PackageError,
    TableState,
)


def _declared_nullable(
    source: str, backend: Backend, *, ignore_primary: bool = False
) -> bool | None:
    """Read top-level NULL clauses, optionally ignoring the primary-key marker."""
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
            not ignore_primary
            and word == "primary"
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


def validate_key_nullability_claims(table: TableState, backend: Backend) -> None:
    """Bind effective key flags independently from ordinary declaration spelling."""
    mysql = backend == "mariadb"
    try:
        _, parts, suffix = split_table(table.sql, mysql=mysql)
        required_keys = mysql or _sqlite_required_keys(suffix)
        declarations = {
            ascii_lower(name): part
            for part in parts
            if tokens(part, mysql=mysql)
            and (name := column_name(part, mysql=mysql)) is not None
        }
        members = table_primary_key_members(parts, backend)
        member_names = frozenset(members)
        inline = tuple(
            column.name
            for column in table.columns
            if _inline_key(column.definition, backend) is not None
        )
        if len(inline) > 1 or (inline and members):
            msg = "multiple primary-key declarations require an explicit adapter"
            raise PackageError(msg)
        if any(name not in declarations for name in members):
            msg = "unknown primary-key member requires an explicit adapter"
            raise PackageError(msg)
        for column in table.columns:
            member = ascii_lower(column.name) in member_names
            if _inline_key(column.definition, backend) is None and not member:
                continue
            for definition in (
                column.definition,
                declarations[ascii_lower(column.name)],
            ):
                declared = _declared_nullable(definition, backend, ignore_primary=True)
                key = _inline_key(definition, backend)
                rowid_shape = (
                    not mysql
                    and (
                        (key is not None and key[0] == "asc")
                        or (member and len(members) == 1)
                    )
                    and _sqlite_storage(definition) == "integer"
                )
                nullable = False if required_keys or rowid_shape else declared
                if nullable != column.nullable:
                    msg = f"primary-key nullability differs for {table.name!r}.{column.name!r}"
                    raise PackageError(msg)
    except SchemaError as error:
        msg = f"cannot verify primary-key nullability: {error}"
        raise PackageError(msg) from error


def _sqlite_required_keys(suffix: str) -> bool:
    """Only known STRICT/WITHOUT ROWID options may imply required key storage."""
    options = tuple((t.kind, ascii_lower(t.value)) for t in tokens(suffix))
    if options[-1:] == (("punct", ";"),):
        options = options[:-1]
    without_rowid = (("word", "without"), ("word", "rowid"))
    strict_option = (("word", "strict"),)
    if options not in (
        (),
        strict_option,
        without_rowid,
        (*strict_option, ("punct", ","), *without_rowid),
        (*without_rowid, ("punct", ","), *strict_option),
    ):
        msg = "unsupported SQLite primary-key table options; explicit adapter required"
        raise PackageError(msg)
    return bool(options)
