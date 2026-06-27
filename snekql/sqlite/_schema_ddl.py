"""SQLite schema DDL compilation and scaffold, free of the aiosqlite driver.

The model->DDL compilation and the public ``scaffold`` live here -- separate from
``snekql.sqlite.schema`` -- so importing the SQLite Backend Namespace exposes
``scaffold`` without importing ``aiosqlite``. The optional driver loads only when
a runtime is actually initialized (ADR 0004).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from snekql._scaffold import scaffold_ddl, scaffold_statements
from snekql._schema_dialect import SchemaDialect
from snekql._schema_shape import ColumnShape
from snekql.sqlite._dialect_sql import CURRENT_TIMESTAMP_SQL
from snekql.sqlite.identifiers import quote_identifier
from snekql.storage import CurrentTimestamp

if TYPE_CHECKING:
    from collections.abc import Sequence

    from snekql._schema_plan import PlannedColumn
    from snekql.model import Table


def _requires_not_null(planned_column: PlannedColumn) -> bool:
    column = planned_column.column
    # A table-level composite PRIMARY KEY is always NOT NULL: a STRICT table
    # enforces it on every key column and PRAGMA table_info reports notnull, so
    # those columns are non-nullable regardless of the declared nullability.
    if planned_column.composite_pk:
        return True
    # A single-column primary key is NOT NULL under STRICT unless it is the
    # INTEGER rowid alias -- the one case SQLite leaves nullable on its own (and
    # PRAGMA table_info reports notnull=0). Every other single-column PK (TEXT,
    # BLOB, REAL) is reported notnull=1, so the DDL must emit NOT NULL to match.
    if column.primary_key:
        return column.sqlite_storage_class != "INTEGER"
    # The column DDL and the expected shape share this predicate to stay in
    # lockstep.
    return column.nullable is False


def _compile_column_definition(planned_column: PlannedColumn) -> str:
    column = planned_column.column
    parts = [quote_identifier(planned_column.name), column.sqlite_storage_class]
    # A composite primary key is rendered once as a table-level constraint, so its
    # member columns must not also carry an inline PRIMARY KEY.
    if column.primary_key and not planned_column.composite_pk:
        parts.append("PRIMARY KEY")
    if column.auto_increment:
        parts.append("AUTOINCREMENT")
    if _requires_not_null(planned_column):
        parts.append("NOT NULL")
    if column.server_default is CurrentTimestamp:
        parts.append(f"DEFAULT ({CURRENT_TIMESTAMP_SQL})")
    return " ".join(parts)


def _expected_column_shape(planned_column: PlannedColumn) -> ColumnShape:
    column = planned_column.column
    return ColumnShape(
        name=planned_column.name,
        storage_type=column.sqlite_storage_class,
        nullable=not _requires_not_null(planned_column),
        primary_key=column.primary_key,
        auto_increment=column.auto_increment,
        has_server_default=column.server_default is CurrentTimestamp,
        collation=None,
    )


SCHEMA_DIALECT = SchemaDialect(
    quote_identifier=quote_identifier,
    compile_column_definition=_compile_column_definition,
    expected_column_shape=_expected_column_shape,
    table_suffix="STRICT",
    verifies_foreign_keys=True,
)


def scaffold_sqlite_ddl(models: Sequence[type[Table[Any]]]) -> str:
    """Emit the initial CREATE TABLE (and index) DDL for SQLite models as text."""

    return scaffold_ddl(models, SCHEMA_DIALECT)


def scaffold_sqlite_statements(
    models: Sequence[type[Table[Any]]],
) -> list[tuple[str, str]]:
    """Return (label, DDL) statement pairs for SQLite model creation."""

    return scaffold_statements(models, SCHEMA_DIALECT)
