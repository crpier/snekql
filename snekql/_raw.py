"""Immutable backend-owned SQL declarations, without connection state."""

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast
from warnings import catch_warnings

from pydantic import TypeAdapter, ValidationError

from snekql._telemetry import QueryDiagnostics
from snekql.errors import (
    MultipleResultsError,
    NoResultError,
    QueryConstructionError,
    RawResultShapeError,
    RawResultValidationError,
    _RawValidationDetail,
)
from snekql.model import BackendFamily

type RowMode = Literal["mapping", "tuple"]
type RawOperation = Literal[
    "execute", "fetch_all", "fetch_one", "fetch_one_or_none", "fetch_chunks"
]

type NativeParameters = tuple[object, ...] | dict[str, object] | None


_SAFE_VALIDATION_CODES = {
    code: code
    for code in (
        "missing",
        "int_parsing",
        "int_type",
        "int_from_float",
        "float_parsing",
        "float_type",
        "string_type",
        "string_too_short",
        "string_too_long",
        "bool_parsing",
        "bool_type",
        "tuple_type",
        "list_type",
        "dict_type",
        "model_type",
        "dataclass_type",
        "extra_forbidden",
        "none_required",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "literal_error",
        "value_error",
        "assertion_error",
        "too_short",
        "too_long",
    )
}
"""Reviewed built-in codes; custom and unknown codes never cross the boundary."""


def _validation_details(error: Exception) -> tuple[_RawValidationDetail, ...]:
    """Discard input, context and arbitrary messages, including custom codes."""

    if isinstance(error, ValidationError):
        try:
            return tuple(
                _RawValidationDetail(
                    code=_SAFE_VALIDATION_CODES.get(
                        detail["type"], "custom_validation_error"
                    ),
                    location=tuple("<redacted>" for _ in detail["loc"]),
                )
                for detail in error.errors(
                    include_url=False, include_input=False, include_context=False
                )
            )
        except Exception:
            # Even rendering a user-defined validation context can fail.
            return (_RawValidationDetail(code="custom_validation_error", location=()),)
    return (_RawValidationDetail(code="custom_validation_error", location=()),)


def _snapshot_parameters(
    params: Mapping[str, object] | Sequence[object] | None,
) -> NativeParameters:
    """Capture container membership without rendering rejected keys or values."""

    if params is None:
        snapshot: NativeParameters = None
    elif isinstance(params, Mapping):
        try:
            snapshot = dict(params)
        except Exception:
            msg = "could not snapshot raw parameters"
            raise QueryConstructionError(msg) from None
        if any(not isinstance(key, str) for key in snapshot):
            msg = "raw parameter mapping keys must be strings"
            raise QueryConstructionError(msg)
    elif isinstance(params, Sequence) and not isinstance(
        params, str | bytes | bytearray | memoryview
    ):
        try:
            snapshot = tuple(params)
        except Exception:
            msg = "could not snapshot raw parameters"
            raise QueryConstructionError(msg) from None
    else:
        msg = "raw parameters must be a mapping, positional sequence, or None"
        raise QueryConstructionError(msg)
    return snapshot


@dataclass(frozen=True, repr=False, init=False)
class RawStatement[FamilyT: BackendFamily, RowT]:
    """A statement constructed through a backend's `raw` factory.

    SQL inspection is deliberate through `.sql`. Ordinary representations omit
    statement content. No connection or execution-local state belongs here.
    """

    _adapter: TypeAdapter[object] | None
    _params: NativeParameters
    backend: FamilyT
    row_mode: RowMode
    sql: str

    def __init__(self) -> None:
        msg = "construct statements through the backend raw factory"
        raise QueryConstructionError(msg)


def build_raw[FamilyT: BackendFamily](
    backend: FamilyT,
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None,
    validate: object,
    row_mode: RowMode,
) -> RawStatement[FamilyT, object]:
    """Snapshot membership without decoding values or interpreting SQL text."""

    if not isinstance(sql, str):
        msg = "raw SQL must be a string"
        raise QueryConstructionError(msg)
    if not isinstance(row_mode, str) or row_mode not in ("mapping", "tuple"):
        msg = "raw row mode must be mapping or tuple"
        raise QueryConstructionError(msg)
    adapter: TypeAdapter[object] | None = None
    if validate is not None:
        if not sys.flags.context_aware_warnings:
            msg = "raw validation requires Python context_aware_warnings=1"
            raise QueryConstructionError(msg)
        try:
            # Skip this constructor and the backend factory when resolving
            # forward annotations, just as a direct caller's TypeAdapter would.
            with catch_warnings(action="ignore"):
                adapter = TypeAdapter(validate, _parent_depth=4)
                adapter.rebuild(raise_errors=True, _parent_namespace_depth=4)
        except Exception:
            msg = "could not construct raw result validator"
            raise QueryConstructionError(msg) from None
    snapshot = _snapshot_parameters(params)
    # The factory assigns the family witness and mode before exposing the value.
    statement = cast(
        "RawStatement[FamilyT, object]",
        object.__new__(RawStatement),
    )
    object.__setattr__(statement, "backend", backend)
    object.__setattr__(statement, "sql", sql)
    object.__setattr__(statement, "row_mode", row_mode)
    object.__setattr__(statement, "_params", snapshot)
    object.__setattr__(statement, "_adapter", adapter)
    return statement


@dataclass(repr=False)
class RawPlan:
    """Execution-local metadata and row packaging for a raw declaration."""

    adapter: TypeAdapter[object] | None
    backend: BackendFamily
    operation: RawOperation
    params: NativeParameters
    row_mode: RowMode
    sql: str
    # Result state is fresh for every execution, never stored on the statement.
    additional_results: bool = field(default=False, init=False)
    columns: tuple[str, ...] | None = field(default=None, init=False)
    row_index: int = field(default=0, init=False)

    @property
    def diagnostics(self) -> QueryDiagnostics:
        return QueryDiagnostics("raw execution failed", (), "", raw=True)

    @property
    def fetch_limit(self) -> int | None:
        if self.operation == "execute":
            return 0
        return 2 if self.operation in ("fetch_one", "fetch_one_or_none") else None

    def check_shape(self) -> None:
        """Use fixed reasons, never returned names or SQL expressions."""

        if self.additional_results:
            msg = "raw operations do not support additional results"
            raise RawResultShapeError(msg)
        if self.operation == "execute":
            if self.columns is not None:
                msg = "raw execute does not accept result columns"
                raise RawResultShapeError(msg)
            return
        if self.columns is None:
            msg = "raw fetch requires result columns"
            raise RawResultShapeError(msg)
        if any(not isinstance(column, str) for column in self.columns):
            msg = "raw result has invalid column metadata"
            raise RawResultShapeError(msg)
        if self.row_mode == "mapping" and len(set(self.columns)) != len(self.columns):
            msg = "raw mapping result has duplicate column names"
            raise RawResultShapeError(msg)

    def materialize(self, rows: Sequence[Sequence[object]]) -> object:
        """Decide cardinality before packaging any accepted row."""

        if not rows:
            if self.operation == "fetch_one_or_none":
                return None
            msg = "fetch_one found no row"
            raise NoResultError(msg)
        if len(rows) > 1:
            msg = "raw capped fetch found more than one row"
            raise MultipleResultsError(msg)
        return self.materialize_row(rows[0])

    def materialize_row(self, row: Sequence[object]) -> object:
        if self.columns is None or len(row) != len(self.columns):
            msg = "raw row width does not match result columns"
            raise RawResultShapeError(msg)
        packaged = (
            tuple(row)
            if self.row_mode == "tuple"
            else dict(zip(self.columns, row, strict=True))
        )
        if self.adapter is None:
            return packaged
        if self.operation == "execute":
            msg = "raw execute cannot materialize rows"
            raise RawResultShapeError(msg)
        with catch_warnings(action="ignore"):
            try:
                validated = self.adapter.validate_python(packaged)
            except Exception as e:
                raise RawResultValidationError(
                    operation=self.operation,
                    row_index=self.row_index,
                    details=_validation_details(e),
                ) from None
        if validated is None and self.operation == "fetch_one_or_none":
            raise RawResultValidationError(
                operation=self.operation,
                row_index=self.row_index,
                details=(_RawValidationDetail(code="none_result", location=()),),
            )
        self.row_index += 1
        return validated


def lower_raw(
    statement: RawStatement[BackendFamily, object],
    *,
    backend: BackendFamily,
    operation: RawOperation,
    validate: bool,
) -> RawPlan:
    """Check operation options without executing or mutating the declaration."""

    if statement.backend != backend:
        msg = "raw statement backend does not match transaction"
        raise QueryConstructionError(msg)
    if validate is not True:
        msg = "raw operations require validate=True"
        raise QueryConstructionError(msg)
    params = statement._params  # noqa: SLF001
    return RawPlan(
        adapter=statement._adapter,  # noqa: SLF001
        backend=backend,
        operation=operation,
        sql=statement.sql,
        params=dict(params) if isinstance(params, dict) else params,
        row_mode=statement.row_mode,
    )
