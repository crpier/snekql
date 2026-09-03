"""Public expression annotation interfaces and supported construction paths."""

from types import ModuleType
from typing import Any

from snektest import Param, assert_in, assert_isinstance, assert_raises, test

from snekql import mariadb, sqlite


class _ExpressionUser[S = sqlite.Pending](
    sqlite.Model[S, "_ExpressionUser[sqlite.Fetched]"],
):
    email: _ExpressionUser.Col[str] = sqlite.Text(nullable=False)
    id: _ExpressionUser.Col[int] = sqlite.Integer(nullable=False)


class _ExpressionOrder[S = sqlite.Pending](
    sqlite.Model[S, "_ExpressionOrder[sqlite.Fetched]"],
):
    user_id: _ExpressionOrder.Col[int] = sqlite.Integer(nullable=False)


class _ForgedAggregate(
    sqlite.Aggregate[_ExpressionUser[sqlite.Pending], int],
):
    def __init__(self) -> None:
        pass

    def __column_owner_type__(self) -> _ExpressionUser[sqlite.Pending]:
        raise NotImplementedError

    def __column_value_type__(self) -> int:
        raise NotImplementedError


class _ForgedScalar(sqlite.Scalar[_ExpressionUser[sqlite.Pending], int]):
    def __init__(self) -> None:
        pass

    def __column_owner_type__(self) -> _ExpressionUser[sqlite.Pending]:
        raise NotImplementedError

    def __column_value_type__(self) -> int:
        raise NotImplementedError


class _ForgedJoin(
    sqlite.JoinOn[
        _ExpressionOrder[sqlite.Pending],
        _ExpressionUser[sqlite.Pending],
    ],
):
    def __init__(self) -> None:
        pass

    def __join_on_types__(
        self,
    ) -> tuple[_ExpressionOrder[sqlite.Pending], _ExpressionUser[sqlite.Pending]]:
        raise NotImplementedError


class _ForgedPredicate(sqlite.Predicate[_ExpressionUser[sqlite.Pending]]):
    def __init__(self) -> None:
        pass

    def __compile_predicate_sql__(
        self,
        compiler: Any,
    ) -> tuple[str, tuple[object, ...]]:
        del compiler
        return '1 = 1; DROP TABLE "_expression_user"; --', ()


class _ForgedOrdering(sqlite.OrderBy[_ExpressionUser[sqlite.Pending]]):
    def __init__(self) -> None:
        pass

    def __order_by_owner_type__(self) -> _ExpressionUser[sqlite.Pending]:
        raise NotImplementedError


class _ForgedAssignment(sqlite.Assignment[_ExpressionUser[sqlite.Pending]]):
    def __init__(self) -> None:
        pass

    def __assignment_owner_type__(self) -> _ExpressionUser[sqlite.Pending]:
        raise NotImplementedError


def _filter_by_value[OwnerT, ValueT](
    column: sqlite.ColumnRef[OwnerT, ValueT],
    value: ValueT,
) -> sqlite.Predicate[OwnerT]:
    return column.eq(value)


def _project_column[OwnerT: sqlite.Model[Any, Any], ValueT](
    column: sqlite.ColumnRef[OwnerT, ValueT],
) -> sqlite.Select[ValueT]:
    return sqlite.select(column).all()


@test(
    [
        Param(value=sqlite, name="sqlite"),
        Param(value=mariadb, name="mariadb"),
    ]
)
def public_expression_annotations_cannot_be_constructed(
    namespace: ModuleType,
) -> None:
    """Annotation names cannot create expression nodes with caller-owned state."""

    with assert_raises(TypeError):
        _ = namespace.Aggregate(func="COUNT")
    for name in ("Scalar", "JoinOn", "OrderBy", "Assignment", "Predicate"):
        with assert_raises(TypeError):
            _ = getattr(namespace, name)()


@test()
def column_ref_comparison_helpers_build_predicates() -> None:
    """A read-only column annotation retains equality comparison behavior."""

    predicate = _filter_by_value(_ExpressionUser.email, "alice@example.com")

    assert_isinstance(predicate, sqlite.Predicate)
    assert_in(
        'WHERE ("email" = ?)',
        repr(sqlite.select(_ExpressionUser).where(predicate)),
    )


@test()
def column_ref_projection_helpers_build_selects() -> None:
    """A read-only column annotation remains projectable through `select`."""

    query = _project_column(_ExpressionUser.email)

    assert_in('SELECT "email" FROM "_expression_user"', repr(query))


@test()
def forged_aggregate_is_rejected_during_query_construction() -> None:
    """An aggregate annotation subclass cannot enter private select state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.select(_ForgedAggregate())


@test()
def forged_scalar_projection_is_rejected_during_query_construction() -> None:
    """A scalar annotation subclass cannot enter private projection state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.select(_ExpressionUser.id, _ForgedScalar())


@test()
def forged_scalar_operand_is_rejected_during_predicate_construction() -> None:
    """A scalar annotation subclass cannot enter private predicate state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = _ExpressionUser.id.eq_col(_ForgedScalar())


@test()
def forged_join_is_rejected_during_query_construction() -> None:
    """A join annotation subclass cannot enter private select state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.select(_ExpressionUser).join(
            _ExpressionOrder,
            on=_ForgedJoin(),
        )


@test()
def forged_predicate_is_rejected_during_query_construction() -> None:
    """A predicate annotation subclass cannot enter private select state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.select(_ExpressionUser).where(_ForgedPredicate())


@test()
def forged_ordering_is_rejected_during_query_construction() -> None:
    """An ordering annotation subclass cannot enter private select state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.select(_ExpressionUser).order_by(_ForgedOrdering())


@test()
def forged_assignment_is_rejected_during_query_construction() -> None:
    """An assignment annotation subclass cannot enter private update state."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.update(_ExpressionUser).set(_ForgedAssignment())


@test()
def forged_assignment_is_rejected_by_conflict_action_construction() -> None:
    """A conflict update cannot retain a forged assignment implementation."""

    with assert_raises(sqlite.QueryConstructionError):
        _ = sqlite.DoUpdate(_ForgedAssignment())
