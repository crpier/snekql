"""Bounded named table CHECK transitions, without arbitrary SQL rewriting."""

from typing import Any

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import _bounded_check_expression
from snekql.experimental._migration_sql import ascii_lower, split_table, tokens
from snekql.experimental.migrations import (
    Backend,
    DropCheck,
    Package,
    PackageError,
    TableState,
)

_MIN_NAMED_CHECK_TOKENS = 6
_NAMED_CHECK_PREFIX = 3


def _check_name(table: TableState, definition: str, backend: Backend) -> str:
    """Require one named CHECK and the existing finite expression/work envelope."""
    stream = tokens(definition, mysql=backend == "mariadb")
    end = 0
    for token in stream:
        if definition[end : token.start].strip():
            msg = "CHECK addition comments require an explicit adapter"
            raise PackageError(msg)
        end = token.end
    words = tuple((token.kind, ascii_lower(token.value)) for token in stream)
    if (
        definition[end:].strip()
        or len(stream) < _MIN_NAMED_CHECK_TOKENS
        or words[0] != ("word", "constraint")
        or stream[1].kind != "identifier"
        or not stream[1].value
        or words[2:4] != (("word", "check"), ("punct", "("))
        or words[-1] != ("punct", ")")
    ):
        msg = "CHECK addition requires one named table constraint without suffixes"
        raise PackageError(msg)
    expression = _bounded_check_expression(definition, stream[4:-1])
    pending = [expression]
    columns = {column.name for column in table.columns}
    while pending:
        node = pending.pop()
        if node.operator == "column" and node.value not in columns:
            msg = "CHECK addition references an unmanaged column"
            raise PackageError(msg)
        pending.extend(node.arguments)
    return stream[1].value


def add_check(table: TableState, definition: str, backend: Backend) -> TableState:
    """Append one supported named table CHECK, preserving other declaration facts."""
    try:
        name = _check_name(table, definition, backend)
        stream = tokens(table.sql, mysql=backend == "mariadb")
        names = {
            ascii_lower(stream[i + 1].value)
            for i, token in enumerate(stream[:-1])
            if (token.kind, ascii_lower(token.value)) == ("word", "constraint")
        }
        if ascii_lower(name) in names:
            msg = "CHECK addition requires a new constraint name"
            raise PackageError(msg)
        prefix, parts, suffix = split_table(table.sql, mysql=backend == "mariadb")
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return table.model_copy(
        update={"sql": prefix + "(" + ", ".join((*parts, definition)) + ")" + suffix}
    )


def check_additions(
    current: TableState, desired: TableState, backend: Backend
) -> tuple[TableState, tuple[str, ...]]:
    """Derive only appended CHECKs; removed/replaced constraints remain unresolved."""
    try:
        before = split_table(current.sql, mysql=backend == "mariadb")[1]
        after = split_table(desired.sql, mysql=backend == "mariadb")[1]
    except SchemaError as error:
        raise PackageError(str(error)) from error
    added = tuple(part for part in after if part not in before)
    for definition in added:
        current = add_check(current, definition, backend)
    return current, added


def drop_check(table: TableState, name: str, backend: Backend) -> TableState:
    """Remove exactly one explicitly named, bounded, managed table CHECK."""
    try:
        prefix, parts, suffix = split_table(table.sql, mysql=backend == "mariadb")
        selected = []
        for part in parts:
            stream = tokens(part, mysql=backend == "mariadb")
            if (
                len(stream) >= _NAMED_CHECK_PREFIX
                and stream[0].kind == "word"
                and ascii_lower(stream[0].value) == "constraint"
                and stream[1].value == name
                and stream[2].kind == "word"
                and ascii_lower(stream[2].value) == "check"
            ):
                _check_name(table, part, backend)
                selected.append(part)
        stream = tokens(table.sql, mysql=backend == "mariadb")
        count = sum(
            token.kind == "word"
            and ascii_lower(token.value) == "constraint"
            and ascii_lower(stream[i + 1].value) == ascii_lower(name)
            for i, token in enumerate(stream[:-1])
        )
        if len(selected) != 1 or count != 1:
            msg = "CHECK removal requires exactly one explicitly managed named table CHECK"
            raise PackageError(msg)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return table.model_copy(
        update={
            "sql": prefix
            + "("
            + ", ".join(part for part in parts if part != selected[0])
            + ")"
            + suffix
        }
    )


def check_removals(
    current: TableState, desired: TableState, backend: Backend
) -> tuple[TableState, tuple[str, ...]]:
    """Propose removals; generation never supplies the destructive authorization."""
    try:
        before = split_table(current.sql, mysql=backend == "mariadb")[1]
        after = split_table(desired.sql, mysql=backend == "mariadb")[1]
        removed = []
        for part in before:
            stream = tokens(part, mysql=backend == "mariadb")
            if (
                part not in after
                and len(stream) >= _NAMED_CHECK_PREFIX
                and (stream[0].kind, ascii_lower(stream[0].value))
                == ("word", "constraint")
                and (stream[2].kind, ascii_lower(stream[2].value)) == ("word", "check")
            ):
                name = _check_name(current, part, backend)
                current = drop_check(current, name, backend)
                removed.append(name)
    except SchemaError as error:
        raise PackageError(str(error)) from error
    return current, tuple(removed)


def _named_checks(sql: str, backend: Backend) -> frozenset[str]:
    """Read declared CHECK names without treating strings or other constraints as names."""
    stream = tokens(sql, mysql=backend == "mariadb")
    return frozenset(
        ascii_lower(stream[i + 1].value)
        for i, token in enumerate(stream[:-2])
        if (token.kind, ascii_lower(token.value)) == ("word", "constraint")
        and (stream[i + 2].kind, ascii_lower(stream[i + 2].value)) == ("word", "check")
    )


def removed_check_obstacle(
    package: Package, catalog: list[tuple[Any, ...]]
) -> str | None:
    """Prove explicit negative claims even when the table is later relinquished."""
    removed = {
        (op.table_name, op.check_name)
        for op in package.draft.operations
        if isinstance(op, DropCheck)
    }
    backend = package.target.backend
    try:
        retained = {
            (table.name, name)
            for table in package.target.tables
            if table.name in {owner for owner, _ in removed}
            for name in _named_checks(table.sql, backend)
        }
        for owner, name in sorted(removed):
            if (owner, ascii_lower(name)) in retained:
                continue
            matches = [
                row
                for row in catalog
                if row[0] == ("table" if backend == "sqlite" else "BASE TABLE")
                and ascii_lower(row[1]) == ascii_lower(owner)
            ]
            if len(matches) != 1 or ascii_lower(name) in _named_checks(
                matches[0][3 if backend == "sqlite" else 2], backend
            ):
                return f"removed CHECK postcondition failed: {owner!r}.{name!r} remains or its owner is unavailable"
    except SchemaError as error:
        return f"cannot verify removed CHECK: {error}"
    return None
