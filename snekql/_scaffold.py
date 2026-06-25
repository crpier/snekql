"""Dev-time schema scaffold: model -> initial CREATE TABLE DDL as text.

The scaffold removes the tedium of hand-writing the first ``CREATE TABLE`` for a
Table Model. It reuses the same model->DDL compilation that backs verification's
expected shape, but only ever emits the *initial create* (table plus its
indexes). It does no model-vs-live diffing and generates no ``ALTER`` (see the
ADR 0001 amendment): the output is plain text the author owns and pastes into
their Migration set, append-only and immutable from the moment it is committed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from snekql._schema_compile import (
    compile_create_index_sql,
    compile_create_table_sql,
)
from snekql._schema_plan import build_schema_plan

if TYPE_CHECKING:
    from collections.abc import Sequence

    from snekql._schema_dialect import SchemaDialect
    from snekql.model import Table


def scaffold_statements(
    models: Sequence[type[Table[Any]]],
    dialect: SchemaDialect,
) -> list[tuple[str, str]]:
    """Return ordered (label, DDL) pairs creating each model's table and indexes.

    Each table is one statement and each index another, because a single
    Migration body runs exactly one statement. The label is a stable, readable
    suffix (the table or index name) a caller can fold into Migration names.
    """

    plan = build_schema_plan(models)
    statements: list[tuple[str, str]] = []
    for planned_model in plan.models:
        statements.append(
            (
                f"create_{planned_model.table_name}",
                compile_create_table_sql(planned_model, dialect),
            )
        )
        statements.extend(
            (
                f"create_index_{index.name}",
                compile_create_index_sql(planned_model.table_name, index, dialect),
            )
            for index in planned_model.indexes
        )
    return statements


def scaffold_ddl(
    models: Sequence[type[Table[Any]]],
    dialect: SchemaDialect,
) -> str:
    """Render the scaffolded statements as a single semicolon-terminated text."""

    statements = scaffold_statements(models, dialect)
    if not statements:
        return ""
    return ";\n".join(sql for _, sql in statements) + ";"
