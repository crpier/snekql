"""Validate and lower bounded literal server defaults."""

from dataclasses import dataclass
from typing import Any, Literal

from snekql._check_catalog import parse_default_literal
from snekql.defaults import LiteralDefault
from snekql.errors import ModelDeclarationError, SnekqlError
from snekql.storage import (
    Attr,
    StorageBackend,
    _annotation_core_types,
    _extract_logical_type,
    _json_payload_annotation,
    _resolve_model_hint,
)


@dataclass(frozen=True)
class LiteralDefaultShape:
    """An encoded literal with the catalog grammar that can verify it."""

    backend: StorageBackend
    value: object


def bind_literal_default(  # noqa: C901
    column: Attr[Any, Any, Any, Any, Any], backend: StorageBackend
) -> None:
    """Snapshot an encoded constant after logical types and nullability are bound."""
    declaration = column.server_default
    if not isinstance(declaration, LiteralDefault):
        return
    if column.owner is None or column.name is None:
        msg = "LiteralDefault requires a bound column"
        raise ModelDeclarationError(msg)
    annotation = _extract_logical_type(
        _resolve_model_hint(column.owner, column.name), column.name
    )
    logical_types = _annotation_core_types(annotation)
    if (
        _json_payload_annotation(annotation)[0]
        or len(logical_types) != 1
        or logical_types[0] not in (int, bool, str)
        or column.storage_type_name not in ("Integer", "Boolean", "Text", "LongText")
        or (logical_types[0] is str)
        != (column.storage_type_name in ("Text", "LongText"))
    ):
        msg = "LiteralDefault requires ordinary integer, Boolean, or text storage"
        raise ModelDeclarationError(msg)
    if column.auto_increment:
        msg = "LiteralDefault cannot be combined with auto_increment"
        raise ModelDeclarationError(msg)
    if declaration.value is None and (
        column.nullable is not True or column.primary_key
    ):
        msg = "LiteralDefault(None) requires a nullable non-primary-key column"
        raise ModelDeclarationError(msg)
    if (
        declaration.value is not None
        and type(declaration.value) is not logical_types[0]
    ):
        msg = "LiteralDefault value must match the column logical type"
        raise ModelDeclarationError(msg)
    try:
        encoded = column.encode(
            column.validate_model_value(declaration.value), backend=backend
        )
        if isinstance(encoded, str):
            encoded.encode("utf-8")
    except (SnekqlError, UnicodeError) as e:
        msg = "LiteralDefault value cannot be encoded"
        raise ModelDeclarationError(msg) from e
    if type(encoded) not in (int, bool, str, type(None)):
        msg = "LiteralDefault requires an integer or text wire value"
        raise ModelDeclarationError(msg)
    if (
        isinstance(encoded, str)
        and column.text_length is not None
        and len(encoded) > column.text_length
    ):
        msg = "LiteralDefault exceeds the declared text length"
        raise ModelDeclarationError(msg)
    column.server_default = LiteralDefault(
        int(encoded) if isinstance(encoded, bool) else encoded
    )


def render_literal_default(
    default: LiteralDefault[object], backend: StorageBackend
) -> str:
    """Quote complete DDL constants without SQL-mode-dependent backslash escaping."""
    value = default.value
    if value is None:
        return "NULL"
    if isinstance(value, str):
        if backend == "mariadb":
            return f"(CONVERT(X'{value.encode('utf-8').hex()}' USING utf8mb4))"
        if "\0" in value:
            return f"(CAST(X'{value.encode('utf-8').hex()}' AS TEXT))"
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def compare_literal_default(
    expected: LiteralDefaultShape, actual: object, *, nullable: bool
) -> tuple[Literal["matched", "drift", "unchecked"], str]:
    """Compare bounded constants without certifying unknown server expressions."""
    if actual is None:
        matches = expected.backend == "mariadb" and expected.value is None and nullable
    elif actual == "CurrentTimestamp":
        matches = False
    elif isinstance(actual, str):
        parsed = parse_default_literal(actual, mariadb=expected.backend == "mariadb")
        if parsed is None:
            return (
                "unchecked",
                "Server default expression is outside the supported literal grammar",
            )
        matches = (
            type(expected.value) is type(parsed.value)
            and expected.value == parsed.value
        )
    else:
        return "unchecked", "Server default metadata is unavailable"
    return (
        "matched" if matches else "drift"
    ), f"server default expected {expected.value!r}, found {actual!r}"
