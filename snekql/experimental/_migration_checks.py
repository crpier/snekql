"""Bounded named table CHECK additions, without arbitrary SQL rewriting."""

from snekql.errors import SchemaError
from snekql.experimental._migration_mariadb import _bounded_check_expression
from snekql.experimental._migration_sql import ascii_lower, split_table, tokens
from snekql.experimental.migrations import Backend, PackageError, TableState

_MIN_NAMED_CHECK_TOKENS = 6


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
