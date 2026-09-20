"""Comparison encoders shared by SQL operands and derived output references."""

from collections.abc import Callable

from snekql._dialect_expr import ComparisonEncoder, SqlCompilable
from snekql._query_dialect import QueryDialect
from snekql._query_state import Selectable, require_field
from snekql.errors import QueryCompilationError
from snekql.expressions import _Aggregate, _Scalar


def _predicate_value_encoder(
    selectable: Selectable,
    dialect: QueryDialect,
) -> Callable[[object], object]:
    """Build the value encoder for a predicate operand.

    A column encodes comparison values through its own logical codec. An
    aggregate's comparison value follows its result type: `COUNT`/`AVG`
    compare against a plain `int`/`float` and pass through unencoded, while
    `MIN`/`MAX` reuse the wrapped column's encoder (so a `datetime` `MIN`
    bound is serialized correctly). `SUM` uses the dialect's result-domain
    encoder because native numeric totals can outgrow their input storage.
    """

    if isinstance(selectable, _Scalar):
        msg = "a scalar subquery is not a value-encoding operand"
        raise QueryCompilationError(msg)
    if isinstance(selectable, ComparisonEncoder):
        return selectable.__encode_comparison__
    if isinstance(selectable, SqlCompilable):
        # A dialect expression owns its own value type (its `__decode__`), so its
        # comparison value passes through unencoded; the leaf, not a column codec,
        # defines what that operand compares against.
        return lambda value: value
    if isinstance(selectable, _Aggregate):
        if selectable.func in {"COUNT", "AVG"}:
            return lambda value: value
        wrapped = require_field(selectable.column)
        if selectable.func == "SUM":
            return lambda value: dialect.encode_sum_value(wrapped, value)
        return lambda value: dialect.encode_column_value(wrapped, value)
    column = selectable
    return lambda value: dialect.encode_column_value(column, value)
