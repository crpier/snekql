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

from snekql._check_catalog import CheckShape
from snekql._checks import render_check
from snekql._schema_shape import (
    ForeignKeyShape,
    TableShape,
)
from snekql.model import require_model_backend

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
        f"FOREIGN KEY ({', '.join(quote(name) for name in foreign_key.column_names)}) "
        f"REFERENCES {quote(foreign_key.target_table)} "
        f"({', '.join(quote(name) for name in foreign_key.target_columns)})"
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
    definitions.extend(
        f"CONSTRAINT {dialect.quote_identifier(check.name)} CHECK ({render_check(check.expression, dialect.quote_identifier, require_model_backend(planned_model.model))})"
        for check in planned_model.checks
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
    prefixes = index.prefix_lengths or (None,) * len(index.column_names)
    column_sql = ", ".join(
        quote(column_name) + (f"({prefix})" if prefix is not None else "")
        for column_name, prefix in zip(index.column_names, prefixes, strict=True)
    )
    predicate_sql = (
        ""
        if index.where is None
        else " WHERE " + render_check(index.where, quote, "sqlite")
    )
    return (
        f"CREATE {unique_sql}INDEX {quote(index.name)} "
        f"ON {quote(table_name)} ({column_sql}){predicate_sql}"
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
                constraint_id=str(constraint_id),
                position=position,
                column_name=column_name,
                target_table=foreign_key.target_table,
                target_column=target_column,
                on_delete=dialect.normalize_foreign_key_action(foreign_key.on_delete),
                on_update=dialect.normalize_foreign_key_action(foreign_key.on_update),
            )
            for constraint_id, foreign_key in enumerate(planned_model.foreign_keys)
            for position, (column_name, target_column) in enumerate(
                zip(foreign_key.column_names, foreign_key.target_columns, strict=True)
            )
        )
    return TableShape(
        table_name=planned_model.table_name,
        columns=tuple(
            dialect.expected_column_shape(planned_column)
            for planned_column in planned_model.columns
        ),
        indexes=tuple(
            dialect.expected_index_shape(index) for index in planned_model.indexes
        ),
        foreign_keys=foreign_keys,
        storage_options=(dialect.table_suffix,),
        checks=tuple(
            CheckShape(check.name, check.expression) for check in planned_model.checks
        ),
    )
