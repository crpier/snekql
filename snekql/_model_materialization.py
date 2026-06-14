"""Shared Table Model row encoding and fetched-row materialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from snekql.errors import ModelDeclarationError, QueryConstructionError
from snekql.storage import MISSING, Attr, StorageBackend


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
        encoded_row[name] = column.encode(value, backend=backend)
    return model_class, encoded_row


def decode_model_row(
    model: type[object],
    row: Mapping[str, object],
    *,
    backend: StorageBackend,
    validate: bool = True,
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
        assert name in remaining_values, (  # noqa: S101
            f"missing database value for {name!r}"
        )
        value = column.decode(
            remaining_values.pop(name),
            backend=backend,
            validate=validate,
        )
        setattr(model_instance, name, value)
    assert not remaining_values, (  # noqa: S101
        f"unknown database values: {', '.join(sorted(remaining_values))}"
    )
    storage["_snekql_frozen"] = True
    return model_instance
