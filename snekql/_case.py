"""Validate searched CASE ownership and native branch contracts."""

from typing import Any, cast

from snekql._query_state import (
    require_column_model,
    require_field,
    selectable_owner_model,
)
from snekql._value_expression import (
    CaseRoot,
    ExpressionMethods,
    ValueExpression,
    _encode_native_literal,
)
from snekql.errors import QueryConstructionError
from snekql.expressions import (
    ColumnComparisonPredicate,
    Predicate,
    _require_predicate_node,
    _Scalar,
)
from snekql.model import require_model_backend


def _condition_inputs(condition: Predicate[Any]) -> tuple[object, ...]:
    """Keep CASE conditions row-local and expose both sides of column comparisons."""
    node = _require_predicate_node(condition)
    if node.__predicate_subquery_arity__ is not None or (
        isinstance(node, ColumnComparisonPredicate) and isinstance(node.other, _Scalar)
    ):
        msg = "CASE conditions do not yet support subqueries"
        raise QueryConstructionError(msg)
    columns: tuple[object, ...] = ()
    for operand in node.__predicate_grouping_operands__():
        if isinstance(operand, ValueExpression):
            columns = (*columns, *operand.__referenced_columns__())
        else:
            columns = (*columns, require_field(operand))
    for child in node.__predicate_children__():
        columns = (*columns, *_condition_inputs(child))
    return columns


def build_case[OwnerT](
    condition: Predicate[OwnerT], *, then: object, otherwise: object, backend: str
) -> ValueExpression[OwnerT, Any]:
    """Infer a native result domain without allowing SQL coercion of branches."""
    columns = _condition_inputs(condition)
    if not columns:
        msg = "CASE requires a condition owned by one query source"
        raise QueryConstructionError(msg)
    owner = require_column_model(require_field(columns[0]))
    if require_model_backend(owner) != backend:
        msg = "CASE condition belongs to another backend"
        raise QueryConstructionError(msg)
    if any(
        require_column_model(require_field(column)) is not owner for column in columns
    ):
        msg = "CASE conditions must reference one query source"
        raise QueryConstructionError(msg)
    branches = tuple(
        branch.__value_operand__() if isinstance(branch, ExpressionMethods) else branch
        for branch in (then, otherwise)
    )
    domains = {
        branch.value_type if isinstance(branch, ValueExpression) else type(branch)
        for branch in branches
        if branch is not None
    }
    if domains == {int, float} and not any(
        isinstance(branch, ValueExpression) and branch.value_type is int
        for branch in branches
    ):
        domains = {float}
    if len(domains) != 1 or not domains <= {int, float, str}:
        msg = "CASE requires compatible native branches and at least one typed branch"
        raise QueryConstructionError(msg)
    for branch in branches:
        if (
            isinstance(branch, ValueExpression)
            and selectable_owner_model(branch) is not owner
        ):
            msg = "CASE branches must reference the condition's query source"
            raise QueryConstructionError(msg)
    value_type = cast("type[int | float | str]", domains.pop())
    encoded = tuple(
        branch
        if isinstance(branch, ValueExpression)
        else _encode_native_literal(value_type, branch)
        for branch in branches
    )
    normalized = tuple(
        float(branch) if value_type is float and type(branch) is int else branch
        for branch in encoded
    )
    return ValueExpression(
        column=CaseRoot(
            condition=condition,
            condition_columns=columns,
            then=normalized[0],
            otherwise=normalized[1],
        ),
        owner=cast("type[OwnerT]", owner),
        value_type=value_type,
        nullable=any(
            branch.nullable if isinstance(branch, ValueExpression) else branch is None
            for branch in branches
        ),
    )
