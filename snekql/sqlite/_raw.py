"""Native sqlite SQL declarations."""

from collections.abc import Mapping, Sequence
from typing import Literal, overload

from snekql._raw import RawStatement as _RawStatement
from snekql._raw import RowMode, build_raw

type RawStatement[RowT] = _RawStatement[Literal["sqlite"], RowT]


@overload
def raw(
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: None = None,
    row_mode: Literal["mapping"] = "mapping",
) -> RawStatement[dict[str, object]]: ...


@overload
def raw(
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: None = None,
    row_mode: Literal["tuple"],
) -> RawStatement[tuple[object, ...]]: ...


@overload
def raw(
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: None = None,
    row_mode: RowMode,
) -> RawStatement[dict[str, object] | tuple[object, ...]]: ...


@overload
def raw[RowT](
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: type[RowT],
    row_mode: RowMode = "mapping",
) -> RawStatement[RowT]: ...


@overload
def raw(
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: object,
    row_mode: RowMode = "mapping",
) -> RawStatement[object]: ...


def raw(
    sql: str,
    *,
    params: Mapping[str, object] | Sequence[object] | None = None,
    validate: object = None,
    row_mode: RowMode = "mapping",
) -> RawStatement[object]:
    """Declare trusted SQL with native parameters, without database IO.

    Values belong in parameters, never interpolated into SQL. Each Transaction
    call executes anew. Omitted parameters differ from supplied empty containers.
    Transaction-control SQL and changes to runtime session settings are unsupported.
    Non-None result contracts require Python context_aware_warnings=1 at startup.

    >>> raw("SELECT 1 AS answer").sql
    'SELECT 1 AS answer'
    """

    return build_raw("sqlite", sql, params=params, validate=validate, row_mode=row_mode)
