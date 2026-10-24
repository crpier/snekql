"""Bounded named index changes, explicit deletion and negative endpoint evidence."""

from typing import Any

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import ascii_lower, tokens
from snekql.experimental.migrations import (
    AdoptTable,
    Backend,
    CreateTable,
    DropIndex,
    Package,
    PackageError,
    TableState,
)


def _parse_index_name(sql: str, table: TableState, backend: Backend) -> str:
    """Accept only unconditional compiler-shaped CREATE [UNIQUE] INDEX declarations."""
    stream = tokens(sql, mysql=backend == "mariadb")
    end = 0
    for token in stream:
        if sql[end : token.start].strip():
            msg = "comments require an explicit adapter"
            raise ValueError(msg)
        end = token.end
    if sql[end:].strip():
        msg = "comments require an explicit adapter"
        raise ValueError(msg)
    offset = int((stream[1].kind, ascii_lower(stream[1].value)) == ("word", "unique"))
    words = tuple((t.kind, ascii_lower(t.value)) for t in stream)
    if (
        words[0] != ("word", "create")
        or words[1 + offset] != ("word", "index")
        or words[3 + offset] != ("word", "on")
    ):
        msg = "expected unconditional CREATE INDEX"
        raise ValueError(msg)
    name, owner = stream[2 + offset], stream[4 + offset]
    if (
        name.kind != "identifier"
        or not name.value
        or owner.kind != "identifier"
        or owner.value != table.name
    ):
        msg = "index name or owner differs"
        raise ValueError(msg)
    if words[5 + offset] != ("punct", "(") or words[-1] != ("punct", ")"):
        msg = "expected whole-column index members"
        raise ValueError(msg)
    members = stream[6 + offset : -1]
    columns = {column.name for column in table.columns}
    if (
        not members
        or len(members) % 2 != 1
        or any(
            (token.kind != "identifier" or token.value not in columns)
            if index % 2 == 0
            else (token.kind, token.value) != ("punct", ",")
            for index, token in enumerate(members)
        )
    ):
        msg = "unsupported index members, predicate or options"
        raise ValueError(msg)
    return name.value


def _index_name(sql: str, table: TableState, backend: Backend) -> str:
    try:
        return _parse_index_name(sql, table, backend)
    except (SchemaError, IndexError, ValueError) as error:
        msg = f"unsupported index addition: {error}; explicit adapter required"
        raise PackageError(msg) from error


def add_index(table: TableState, sql: str, backend: Backend) -> TableState:
    """Append a distinct declared index; execution must create it rather than adopt it."""
    name = _index_name(sql, table, backend)
    names = {_index_name(existing, table, backend) for existing in table.indexes}
    if ascii_lower(name) in {ascii_lower(existing) for existing in names}:
        msg = "index addition requires a new managed index name"
        raise PackageError(msg)
    return table.model_copy(update={"indexes": (*table.indexes, sql)})


def drop_index(table: TableState, name: str, backend: Backend) -> TableState:
    """Remove exactly one explicitly recorded, bounded secondary index."""
    matching = [
        sql for sql in table.indexes if _index_name(sql, table, backend) == name
    ]
    if len(matching) != 1:
        msg = "index removal requires exactly one explicitly managed index"
        raise PackageError(msg)
    return table.model_copy(
        update={"indexes": tuple(sql for sql in table.indexes if sql != matching[0])}
    )


def index_removals(
    current: TableState, desired: TableState, backend: Backend
) -> tuple[TableState, tuple[str, ...]]:
    """Propose removals without authorizing them or changing the caller's snapshot."""
    names = tuple(
        _index_name(sql, current, backend)
        for sql in current.indexes
        if sql not in desired.indexes
    )
    for name in names:
        current = drop_index(current, name, backend)
    return current, names


def validate_index_dependencies(
    package: Package, objects: list[tuple[Any, ...]]
) -> None:
    """Refuse removal on a referenced table, including unowned and legacy-quoted FKs."""
    owners = {
        ascii_lower(op.table_name)
        for op in package.draft.operations
        if isinstance(op, DropIndex)
    }
    if not owners:
        return
    names = {
        ascii_lower(op.index_name)
        for op in package.draft.operations
        if isinstance(op, DropIndex)
    }
    sources = [
        (row[0], row[3] if package.target.backend == "sqlite" else row[2])
        for row in objects
    ]
    sources.extend(
        ("table", table.sql)
        for table in (*package.draft.before.tables, *package.target.tables)
    )
    sources.extend(
        ("table", op.table.sql)
        for op in package.draft.operations
        if isinstance(op, CreateTable | AdoptTable)
    )
    modes = (False, True) if package.target.backend == "mariadb" else (False,)
    try:
        for kind, sql in sources:
            for mysql in modes:
                stream = tokens(sql, mysql=mysql) if sql else ()
                values = {ascii_lower(token.value) for token in stream}
                foreign_key = any(
                    token.kind == "word" and ascii_lower(token.value) == "references"
                    for token in stream
                )
                if (foreign_key and values & owners) or (
                    kind in {"view", "trigger", "VIEW"} and values & names
                ):
                    msg = "index removal has a possible foreign-key or stored-object dependency; explicit adapter required"
                    raise PackageError(msg)
    except SchemaError as error:
        msg = f"index removal cannot verify dependencies: {error}"
        raise PackageError(msg) from error


def removed_indexes(package: Package) -> tuple[tuple[str, str], ...]:
    """Select negative endpoint claims, excluding explicitly recorded replacements."""
    removed = {
        (op.table_name, op.index_name)
        for op in package.draft.operations
        if isinstance(op, DropIndex)
    }
    retained = (
        {
            (table.name, ascii_lower(_index_name(sql, table, package.target.backend)))
            for table in package.target.tables
            if table.name in {owner for owner, _ in removed}
            for sql in table.indexes
        }
        if removed
        else set()
    )
    return tuple(
        sorted(
            (owner, name)
            for owner, name in removed
            if (owner, ascii_lower(name)) not in retained
        )
    )


def validate_removed_sqlite_indexes(
    package: Package, objects: list[tuple[Any, ...]]
) -> None:
    """Require physical absence before the SQLite completion receipt can commit."""
    for owner, name in removed_indexes(package):
        if not any(
            row[0] == "table" and ascii_lower(row[1]) == ascii_lower(owner)
            for row in objects
        ) or any(
            row[0] == "index"
            and ascii_lower(row[1]) == ascii_lower(name)
            and ascii_lower(row[2]) == ascii_lower(owner)
            for row in objects
        ):
            msg = f"removed index postcondition failed: {owner!r}.{name!r} remains or its owner is unavailable"
            raise PackageError(msg)
