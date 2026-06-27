"""Backend-neutral schema DDL and expected-shape compilation.

Mirrors :mod:`snekql._query_compile`: one shared compiler turns a
:class:`~snekql._schema_plan.PlannedModel` into backend DDL and the semantic
:class:`~snekql._schema_shape.TableShape`, parameterized by a
:class:`~snekql._schema_dialect.SchemaDialect`. The column-level work that truly
diverges between backends is delegated back to the dialect's callbacks; the
foreign-key, index, table, and shape skeletons live here once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from snekql._schema_shape import (
    ForeignKeyShape,
    IndexShape,
    TableShape,
)

if TYPE_CHECKING:
    from snekql._schema_dialect import SchemaDialect
    from snekql._schema_plan import PlannedForeignKey, PlannedModel
    from snekql.indexes import NormalizedIndex


def compile_foreign_key_constraint(
    foreign_key: PlannedForeignKey,
    dialect: SchemaDialect,
) -> str:
    """Render a table-level FOREIGN KEY ... REFERENCES constraint."""

    quote = dialect.quote_identifier
    return (
        f"FOREIGN KEY ({quote(foreign_key.column_name)}) "
        f"REFERENCES {quote(foreign_key.target_table)} "
        f"({quote(foreign_key.target_column)})"
    )


def compile_create_table_sql(
    planned_model: PlannedModel,
    dialect: SchemaDialect,
) -> str:
    """Render CREATE TABLE, delegating each column definition to the dialect."""

    definitions = [
        dialect.compile_column_definition(planned_column)
        for planned_column in planned_model.columns
    ]
    definitions.extend(
        compile_foreign_key_constraint(foreign_key, dialect)
        for foreign_key in planned_model.foreign_keys
    )
    table_body = ", ".join(definitions)
    return (
        f"CREATE TABLE {dialect.quote_identifier(planned_model.table_name)} "
        f"({table_body}) {dialect.table_suffix}"
    )


def compile_create_index_sql(
    table_name: str,
    index: NormalizedIndex,
    dialect: SchemaDialect,
) -> str:
    """Render CREATE [UNIQUE] INDEX for one normalized index."""

    quote = dialect.quote_identifier
    unique_sql = "UNIQUE " if index.unique else ""
    column_sql = ", ".join(quote(column_name) for column_name in index.column_names)
    return (
        f"CREATE {unique_sql}INDEX {quote(index.name)} "
        f"ON {quote(table_name)} ({column_sql})"
    )


def expected_table_shape(
    planned_model: PlannedModel,
    dialect: SchemaDialect,
) -> TableShape:
    """Build the semantic shape a model expects from a live table.

    Foreign keys are only included when the backend verifies them; backends that
    cannot model their catalog's implicit constraint indexes report an empty FK
    tuple via ``verifies_foreign_keys=False``.
    """

    foreign_keys: tuple[ForeignKeyShape, ...] = ()
    if dialect.verifies_foreign_keys:
        foreign_keys = tuple(
            ForeignKeyShape(
                column_name=foreign_key.column_name,
                target_table=foreign_key.target_table,
                target_column=foreign_key.target_column,
            )
            for foreign_key in planned_model.foreign_keys
        )
    return TableShape(
        table_name=planned_model.table_name,
        columns=tuple(
            dialect.expected_column_shape(planned_column)
            for planned_column in planned_model.columns
        ),
        indexes=tuple(
            IndexShape(
                name=index.name,
                column_names=index.column_names,
                unique=index.unique,
            )
            for index in planned_model.indexes
        ),
        foreign_keys=foreign_keys,
        storage_options=(dialect.table_suffix,),
    )
