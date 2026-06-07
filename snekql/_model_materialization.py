"""Shared Table Model row encoding and fetched-row materialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from snekql.errors import (
    ModelDeclarationError,
    ModelValidationError,
    QueryConstructionError,
)
from snekql.storage import MISSING, Attr

type StorageBackend = Literal["mariadb", "sqlite"]


def _require_model_columns(
    model: type[object],
) -> dict[str, Attr[Any, Any, Any, Any, Any]]:
    columns = getattr(model, "__snekql_columns__", None)
    if not isinstance(columns, dict):
        msg = "schema setup requires snekql table models"
        raise ModelDeclarationError(msg)
    return cast("dict[str, Attr[Any, Any, Any, Any, Any]]", columns)


def _require_insert_model(row: object) -> type[object]:
    model_class = row.__class__
    try:
        _ = _require_model_columns(model_class)
    except ModelDeclarationError as error:
        msg = "insert requires a snekql model instance"
        raise QueryConstructionError(msg) from error
    return model_class


def encode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
    *,
    backend: StorageBackend,
) -> object:
    """Encode one logical model value through a backend-specific column codec."""

    if backend == "mariadb":
        return column.encode_mariadb(value)
    return column.encode_sqlite(value)


def decode_column_value(
    column: Attr[Any, Any, Any, Any, Any],
    value: object,
    *,
    backend: StorageBackend,
) -> object:
    """Decode one database value through a backend-specific column codec."""

    if backend == "mariadb":
        return column.decode_mariadb(value)
    return column.decode_sqlite(value)


def encode_model_row(
    row: object,
    *,
    backend: StorageBackend,
) -> tuple[type[object], dict[str, object]]:
    """Encode a Pending Model into table metadata and backend row values."""

    model_class = _require_insert_model(row)
    encoded_row: dict[str, object] = {}
    for name, column in _require_model_columns(model_class).items():
        value = getattr(row, name)
        if value is MISSING:
            continue
        encoded_row[name] = encode_column_value(column, value, backend=backend)
    return model_class, encoded_row


def decode_model_row(
    model: type[object],
    row: Mapping[str, object],
    *,
    backend: StorageBackend,
) -> object:
    """Materialize a Fetched Model from backend row values."""

    remaining_values = dict(row)
    model_instance = object.__new__(model)
    storage = cast(
        "dict[str, object]",
        object.__getattribute__(model_instance, "__dict__"),
    )
    storage["_snekql_frozen"] = False
    storage["_snekql_state"] = "Fetched"
    for name, column in _require_model_columns(model).items():
        if name not in remaining_values:
            msg = f"missing database value for {name!r}"
            raise ModelValidationError(msg)
        value = decode_column_value(
            column,
            remaining_values.pop(name),
            backend=backend,
        )
        setattr(model_instance, name, value)
    if remaining_values:
        names = ", ".join(sorted(remaining_values))
        msg = f"unknown database values: {names}"
        raise ModelValidationError(msg)
    storage["_snekql_frozen"] = True
    return model_instance
