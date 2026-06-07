"""Shared model-derived schema planning for backend schema startup."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from snekql.errors import SchemaError
from snekql.indexes import NormalizedIndex
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr, SchemaPolicy


@dataclass(frozen=True)
class PlannedColumn:
    """One model column resolved for schema startup."""

    column: Attr[Any, Any, Any, Any, Any]
    name: str


@dataclass(frozen=True)
class PlannedModel:
    """One table model's backend-neutral schema startup inputs."""

    columns: tuple[PlannedColumn, ...]
    indexes: tuple[NormalizedIndex, ...]
    model: type[Table[Any]]
    table_name: str


@dataclass(frozen=True)
class SchemaPlan:
    """Ordered schema startup plan shared by backend adapters."""

    models: tuple[PlannedModel, ...]


def _column_unique_indexes(
    table_name: str,
    columns: tuple[PlannedColumn, ...],
) -> tuple[NormalizedIndex, ...]:
    return tuple(
        NormalizedIndex(
            column_names=(planned_column.name,),
            name=f"ux_{table_name}_{planned_column.name}",
            unique=True,
        )
        for planned_column in columns
        if planned_column.column.unique
    )


def _model_indexes(
    model: type[Table[Any]],
    table_name: str,
    columns: tuple[PlannedColumn, ...],
) -> tuple[NormalizedIndex, ...]:
    table_indexes = getattr(model, "__snekql_indexes__", ())
    return (*_column_unique_indexes(table_name, columns), *table_indexes)


def _plan_model(model: type[Table[Any]]) -> PlannedModel:
    table_name = require_model_table_name(model)
    columns = tuple(
        PlannedColumn(column=column, name=name)
        for name, column in require_model_columns(model).items()
    )
    return PlannedModel(
        columns=columns,
        indexes=_model_indexes(model, table_name, columns),
        model=model,
        table_name=table_name,
    )


def build_schema_plan(models: Sequence[type[Table[Any]]]) -> SchemaPlan:
    """Resolve and validate model-derived schema startup metadata once."""

    planned_models = tuple(_plan_model(model) for model in models)
    table_names: set[str] = set()
    index_names: set[str] = set()
    for planned_model in planned_models:
        if planned_model.table_name in table_names:
            msg = f"duplicate table name: {planned_model.table_name!r}"
            raise SchemaError(msg)
        table_names.add(planned_model.table_name)
        for index in planned_model.indexes:
            if index.name in index_names:
                msg = f"duplicate index name: {index.name!r}"
                raise SchemaError(msg)
            index_names.add(index.name)
    return SchemaPlan(models=planned_models)


def validate_schema_policy(schema_policy: SchemaPolicy) -> None:
    """Reject unsupported schema policy values."""

    if schema_policy not in {"strict", "warn"}:
        msg = "schema_policy must be 'strict' or 'warn'"
        raise SchemaError(msg)
