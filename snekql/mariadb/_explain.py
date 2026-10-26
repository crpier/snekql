"""Validate and expose MariaDB JSON plan evidence without interpreting policy."""

lazy import json
lazy from math import isfinite
lazy from typing import cast

lazy from snekql._explain_types import ExplainFormat, MariaDBPlanNode, MariaDBQueryPlan
lazy from snekql.errors import DatabaseRuntimeError


def _text(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None or isinstance(value, str):
        return value
    msg = "unexpected MariaDB query-plan text field"
    raise DatabaseRuntimeError(msg)


def _number(data: dict[str, object], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            if isfinite(number):
                return number
        except OverflowError:
            pass
    msg = "unexpected MariaDB query-plan numeric field"
    raise DatabaseRuntimeError(msg)


def _integer(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None or type(value) is int:
        return value
    msg = "unexpected MariaDB query-plan integer field"
    raise DatabaseRuntimeError(msg)


def _objects(
    data: dict[str, object], path: tuple[str | int, ...]
) -> tuple[MariaDBPlanNode, ...]:
    return tuple(
        node
        for key, value in data.items()
        for node in _contained_objects(value, key, (*path, key))
    )


def _contained_objects(
    value: object, operation: str, path: tuple[str | int, ...]
) -> tuple[MariaDBPlanNode, ...]:
    if isinstance(value, dict):
        return (_node(operation, path, cast("dict[str, object]", value)),)
    if isinstance(value, list):
        return tuple(
            node
            for index, item in enumerate(value)
            for node in _contained_objects(item, operation, (*path, index))
        )
    return ()


def _node(
    operation: str, path: tuple[str | int, ...], data: dict[str, object]
) -> MariaDBPlanNode:
    return MariaDBPlanNode(
        operation=operation,
        path=path,
        children=_objects(data, path),
        table_name=_text(data, "table_name"),
        access_type=_text(data, "access_type"),
        key=_text(data, "key"),
        estimated_rows=_number(data, "rows"),
        estimated_filtered_percent=_number(data, "filtered"),
        actual_rows=_number(data, "r_rows"),
        actual_loops=_integer(data, "r_loops"),
        actual_filtered_percent=_number(data, "r_filtered"),
        total_time_ms=_number(data, "r_total_time_ms"),
        table_time_ms=_number(data, "r_table_time_ms"),
    )


def decode_explain(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    plan_format: ExplainFormat,
) -> MariaDBQueryPlan | None:
    """Tabular plans stay native; JSON plans add an immutable structural view."""
    if plan_format == "native":
        return None
    if (
        len(columns) != 1
        or len(rows) != 1
        or len(rows[0]) != 1
        or not isinstance(rows[0][0], str)
    ):
        msg = "unexpected MariaDB JSON query-plan result shape"
        raise DatabaseRuntimeError(msg)
    native_json = rows[0][0]
    try:
        document = json.loads(native_json)
        if not isinstance(document, dict):
            msg = "unexpected MariaDB JSON query-plan document"
            raise DatabaseRuntimeError(msg)
        return MariaDBQueryPlan(
            roots=_objects(cast("dict[str, object]", document), ()),
            native_json=native_json,
        )
    except ValueError, RecursionError:
        msg = "invalid MariaDB JSON query-plan document"
        raise DatabaseRuntimeError(msg) from None
