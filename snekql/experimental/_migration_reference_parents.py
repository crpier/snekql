"""Observed/projected SQLite referenced-table presence, without adopting parents."""

from collections.abc import Iterator
from itertools import chain
from typing import Any

from snekql.experimental._migration_inline_reference import _reference
from snekql.experimental._migration_sql import Token, ascii_lower, split_table, tokens
from snekql.experimental.migrations import (
    AdoptTable,
    CreateTable,
    Package,
    PackageError,
    TableState,
)


def validate_sqlite_reference_parents(
    package: Package, objects: list[tuple[Any, ...]]
) -> None:
    """Require declared parent tables in observed/projected catalog, not key compatibility."""
    if package.target.backend != "sqlite":
        return
    tables = {ascii_lower(row[1]): row[3] for row in objects if row[0] == "table"}
    for owner, reference in _claims(package):
        if not _ordinary_table(tables.get(reference)):
            msg = f"SQLite referenced parent {reference!r} for {owner!r} requires an observed or explicitly planned base table; no implicit adoption"
            raise PackageError(msg)


def _claims(package: Package) -> Iterator[tuple[str, str]]:
    """Keep before/target/intermediate references despite relinquishment."""
    for table in chain(
        package.draft.before.tables,
        package.target.tables,
        (
            op.table
            for op in package.draft.operations
            if isinstance(op, CreateTable | AdoptTable)
        ),
    ):
        for reference in _parents(table):
            yield table.name, reference


def _parents(table: TableState) -> Iterator[str]:
    """Read claimed inline refs and table FK targets, not unowned extra-field references."""
    for column in table.columns:
        reference = _reference(column.definition)
        if reference is not None:
            yield reference[0]
    for part in split_table(table.sql)[1]:
        stream = tokens(part)
        if stream and (stream[0].kind, ascii_lower(stream[0].value)) == (
            "word",
            "constraint",
        ):
            stream = stream[2:]
        if tuple((t.kind, ascii_lower(t.value)) for t in stream[:2]) == (
            ("word", "foreign"),
            ("word", "key"),
        ):
            yield _target(stream)


def _target(stream: tuple[Token, ...]) -> str:
    """Resolve one unqualified table FK target without claiming referenced key semantics."""
    depth = 0
    positions: list[int] = []
    for index, token in enumerate(stream):
        if token.kind == "punct":
            depth += (token.value == "(") - (token.value == ")")
        if not depth and (token.kind, ascii_lower(token.value)) == (
            "word",
            "references",
        ):
            positions.append(index + 1)
    if len(positions) != 1 or positions[0] >= len(stream):
        msg = "SQLite referenced parent requires one explicit table target; adapter required"
        raise PackageError(msg)
    position = positions[0]
    token = stream[position]
    if (
        token.kind not in {"word", "identifier"}
        or not token.value
        or (
            position + 1 < len(stream)
            and (stream[position + 1].kind, stream[position + 1].value)
            == ("punct", ".")
        )
    ):
        msg = "SQLite referenced parent requires an unqualified identifier; adapter required"
        raise PackageError(msg)
    return ascii_lower(token.value)


def _ordinary_table(sql: str | None) -> bool:
    """Require ordinary CREATE TABLE, not SQLite's table-typed virtual declaration."""
    return isinstance(sql, str) and tuple(
        (t.kind, ascii_lower(t.value)) for t in tokens(sql)[:2]
    ) == (("word", "create"), ("word", "table"))
