"""Bounded MariaDB structural postcondition checks, never data-work inference."""

from itertools import pairwise
from typing import Any

from snekql.errors import SchemaError
from snekql.experimental._migration_sql import (
    column_name,
    required_definition,
    split_table,
    tokens,
)
from snekql.experimental.migrations import Contraction


def _signature(sql: str) -> tuple[tuple[str, str], ...]:
    # Keep quoted text byte-for-byte: do not guess equivalence of escaping modes,
    # collations, codec spellings or version-dependent engine rendering.
    return tuple(
        (
            token.kind,
            sql[token.start : token.end].casefold()
            if token.kind == "word"
            else sql[token.start : token.end],
        )
        for token in tokens(sql, mysql=True)
    )


def _remove_null_default(sql: str) -> str:
    stream = tokens(sql, mysql=True)
    depth = 0
    for left, right in pairwise(stream):
        if left.kind == "punct" and left.value == "(":
            depth += 1
        elif left.kind == "punct" and left.value == ")":
            depth -= 1
        elif (
            depth == 0
            and left.kind == right.kind == "word"
            and left.value.casefold() == "default"
            and right.value.casefold() == "null"
        ):
            return (sql[: left.start] + sql[right.end :]).strip()
    return sql


def _project(sql: str, change: Contraction) -> str:
    prefix, parts, suffix = split_table(sql, mysql=True)
    columns = {column_name(part, mysql=True) for part in parts}
    if not {*change.required, *change.dropped} <= columns:
        msg = "observed contraction columns are missing"
        raise SchemaError(msg)
    revised = []
    for original in parts:
        part = original
        name = column_name(part, mysql=True)
        if name in change.dropped:
            continue
        if name in change.required:
            intended = next(
                column.definition
                for column in change.after.columns
                if column.name == name
            )
            # SHOW CREATE supplies DEFAULT NULL for an implicit nullable default.
            # Do not infer permission to erase an explicitly requested default.
            if _remove_null_default(intended) == intended:
                part = _remove_null_default(part)
            part = required_definition(part, mysql=True)
        revised.append(part)
    return prefix + "(" + ", ".join(revised) + ")" + suffix


def matches_contraction(
    change: Contraction | None, before: list[Any], after: list[Any]
) -> bool:
    """Compare the entire observed catalog to exactly one projected contraction."""
    if change is None or change.defaults:
        # The projection below proves require/drop only. A matching nullability
        # change must not certify a default transition it has not compared.
        return False
    try:
        projected = []
        matched = False
        for kind, name, original_sql in before:
            sql = original_sql
            if kind == "BASE TABLE" and name == change.before.name:
                sql = _project(sql, change)
                matched = True
            projected.append((kind, name, _signature(sql)))
        actual = [(kind, name, _signature(sql)) for kind, name, sql in after]
        return matched and sorted(projected) == sorted(actual)
    except SchemaError, ValueError, TypeError, StopIteration:
        # A non-understood rendering is unresolved evidence, never a best guess.
        return False
