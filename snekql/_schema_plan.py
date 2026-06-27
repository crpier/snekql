"""Shared model-derived schema planning for backend schema startup."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast, get_args, get_origin, get_type_hints

from snekql.errors import SchemaError
from snekql.indexes import NormalizedIndex
from snekql.model import Table, require_model_columns, require_model_table_name
from snekql.storage import Attr, SchemaPolicy


@dataclass(frozen=True)
class PlannedColumn:
    """One model column resolved for schema startup.

    ``composite_pk`` is set when the column is one of several ``primary_key``
    columns making up a multi-column primary key. The backends render such a key
    as a single table-level ``PRIMARY KEY (...)`` constraint rather than an
    inline per-column ``PRIMARY KEY``, so they need to tell the two cases apart.
    """

    column: Attr[Any, Any, Any, Any, Any]
    name: str
    composite_pk: bool = False


@dataclass(frozen=True)
class PlannedForeignKey:
    """One enforced foreign-key relationship resolved for schema startup.

    The local ``column_name`` references ``target_column`` on ``target_table``;
    the target column is the one named explicitly by ``ForeignKey(Target.col)``,
    and the target model is cross-checked against the column's ``FKCol[Target, T]``
    annotation.
    """

    column_name: str
    target_table: str
    target_column: str


@dataclass(frozen=True)
class PlannedModel:
    """One table model's backend-neutral schema startup inputs."""

    columns: tuple[PlannedColumn, ...]
    foreign_keys: tuple[PlannedForeignKey, ...]
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


def _resolve_target_model(model: type[Table[Any]], name: str) -> type[Table[Any]]:
    """Resolve the referenced model from a column's ``FKCol`` annotation."""

    # Resolving annotations needs names visible where the model was declared,
    # plus the model's own name for self-referential column owners
    # (``Order.GenCol[int]``), which is not yet bound while the class body runs.
    captured_localns = cast(
        "dict[str, Any] | None",
        getattr(model, "__snekql_localns__", None),
    )
    localns: dict[str, Any] = {**(captured_localns or {}), model.__name__: model}
    try:
        hints = get_type_hints(model, localns=localns, include_extras=True)
    except Exception as error:
        msg = f"cannot resolve foreign-key annotation for column {name!r}"
        raise SchemaError(msg) from error
    annotation = hints.get(name)
    origin = get_origin(annotation)
    if origin is None or getattr(origin, "__name__", None) != "FKCol":
        msg = f"foreign_key column {name!r} must be annotated as FKCol[Target, T]"
        raise SchemaError(msg)
    target_argument = cast("object", get_args(annotation)[0])
    target_model = get_origin(target_argument) or target_argument
    if not isinstance(target_model, type) or not issubclass(target_model, Table):
        msg = f"foreign-key target for column {name!r} is not a table model"
        raise SchemaError(msg)
    return cast("type[Table[Any]]", target_model)


def _resolve_target_column(
    target_model: type[Table[Any]],
    name: str,
    target_column: Attr[Any, Any, Any, Any, Any],
) -> str:
    """Resolve and validate the FK target column named by ``ForeignKey``.

    The target column is the descriptor passed to ``ForeignKey(Target.col)``; it
    must belong to the annotation's target model (identity, not just name match)
    and be a primary key or carry a unique constraint, since a foreign key can
    only reference a uniquely indexed column.
    """

    target_table = require_model_table_name(target_model)
    target_column_name = next(
        (
            column_name
            for column_name, column in require_model_columns(target_model).items()
            if column is target_column
        ),
        None,
    )
    if target_column_name is None:
        msg = (
            f"foreign-key column {name!r} references a column that is not on "
            f"target table {target_table!r}"
        )
        raise SchemaError(msg)
    if not (target_column.primary_key or target_column.unique):
        msg = (
            f"foreign-key column {name!r} target "
            f"{target_table}.{target_column_name} must be a primary key or unique"
        )
        raise SchemaError(msg)
    return target_column_name


def _plan_foreign_keys(
    model: type[Table[Any]],
    columns: tuple[PlannedColumn, ...],
) -> tuple[PlannedForeignKey, ...]:
    foreign_keys: list[PlannedForeignKey] = []
    for planned_column in columns:
        target_column = planned_column.column.foreign_key_target
        if target_column is None:
            continue
        target_model = _resolve_target_model(model, planned_column.name)
        foreign_keys.append(
            PlannedForeignKey(
                column_name=planned_column.name,
                target_table=require_model_table_name(target_model),
                target_column=_resolve_target_column(
                    target_model,
                    planned_column.name,
                    target_column,
                ),
            ),
        )
    return tuple(foreign_keys)


def _plan_columns(
    model: type[Table[Any]],
) -> tuple[PlannedColumn, ...]:
    model_columns = require_model_columns(model)
    primary_key_count = sum(
        1 for column in model_columns.values() if column.primary_key
    )
    composite = primary_key_count > 1
    if composite:
        offending = next(
            (
                name
                for name, column in model_columns.items()
                if column.primary_key and column.auto_increment
            ),
            None,
        )
        if offending is not None:
            msg = (
                f"column {offending!r} cannot use auto_increment as part of a "
                f"composite primary key on table {require_model_table_name(model)!r}"
            )
            raise SchemaError(msg)
    return tuple(
        PlannedColumn(
            column=column,
            name=name,
            composite_pk=composite and column.primary_key,
        )
        for name, column in model_columns.items()
    )


def _plan_model(model: type[Table[Any]]) -> PlannedModel:
    table_name = require_model_table_name(model)
    columns = _plan_columns(model)
    return PlannedModel(
        columns=columns,
        foreign_keys=_plan_foreign_keys(model, columns),
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
