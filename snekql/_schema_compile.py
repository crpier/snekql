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
    """Render a table-level FOREIGN KEY ... REFERENCES constraint.

    A declared ``on_delete``/``on_update`` appends an ``ON DELETE``/``ON UPDATE``
    clause verbatim; ``None`` renders no clause, leaving the database default
    (``NO ACTION``) so existing scaffolds are byte-for-byte unchanged.
    """

    quote = dialect.quote_identifier
    constraint = (
        f"FOREIGN KEY ({quote(foreign_key.column_name)}) "
        f"REFERENCES {quote(foreign_key.target_table)} "
        f"({quote(foreign_key.target_column)})"
    )
    if foreign_key.on_delete is not None:
        constraint += f" ON DELETE {foreign_key.on_delete}"
    if foreign_key.on_update is not None:
        constraint += f" ON UPDATE {foreign_key.on_update}"
    return constraint


def compile_create_table_sql(
    planned_model: PlannedModel,
    dialect: SchemaDialect,
) -> str:
    """Render CREATE TABLE, delegating each column definition to the dialect."""

    definitions = [
        dialect.compile_column_definition(planned_column)
        for planned_column in planned_model.columns
    ]
    composite_pk_columns = [
        planned_column.name
        for planned_column in planned_model.columns
        if planned_column.composite_pk
    ]
    if composite_pk_columns:
        quoted = ", ".join(
            dialect.quote_identifier(name) for name in composite_pk_columns
        )
        definitions.append(f"PRIMARY KEY ({quoted})")
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
                # An unset action defaults to the catalog's NO ACTION so the
                # expected shape matches what the live PRAGMA reports.
                on_delete=foreign_key.on_delete or "NO ACTION",
                on_update=foreign_key.on_update or "NO ACTION",
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
