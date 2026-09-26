"""Shared definition graphs must not expand nominal owners into repeated trees."""

from typing import Any, ClassVar, Literal

from snektest import assert_eq, test

from snekql import sqlite
from snekql._cte import _Cte
from snekql._output_label import _OutputLabel
from tests.query.test_ctes import ActiveRole, Identifier, Person


def _shared_layer(
    source: _Cte[Literal["sqlite"], Any, Identifier, Any, Any],
    token: _OutputLabel[Any, int, int],
    left_role: type[object],
    right_role: type[object],
    depth: int,
) -> tuple[
    _Cte[Literal["sqlite"], Any, Identifier, Any, Any], _OutputLabel[Any, int, int]
]:
    """Generate dynamic graph depth; nominal typing has separate conformance tests."""
    left = sqlite.alias(source, left_role, name=f"left_{depth}")
    right = sqlite.alias(source, right_role, name=f"right_{depth}")
    value = left.column(token).label("id")
    definition = (
        sqlite.select(left)
        .join(right, on=left.column(token).eq_col(right.column(token)))
        .project(Identifier, id=value)
        .cte(ActiveRole, name=f"layer_{depth}")
    )
    return definition, value


@test(mark="fast")
def shared_cte_graph_has_bounded_nominal_role_work() -> None:
    """Stable role hashing supplies a deterministic budget, not a timing gate."""

    class BudgetedRole(type):
        calls: ClassVar[int] = 0

        def __hash__(cls) -> int:
            BudgetedRole.calls += 1
            if BudgetedRole.calls > 20_000:
                msg = "nominal role hashing budget exhausted"
                raise AssertionError(msg)
            return type.__hash__(cls)

    class LeftRole(metaclass=BudgetedRole):
        pass

    class RightRole(metaclass=BudgetedRole):
        pass

    token: _OutputLabel[Any, int, int] = Person.id.label("id")
    source: _Cte[Literal["sqlite"], Any, Identifier, Any, Any] = (
        sqlite.select(Person)
        .where(Person.id.eq(1))
        .project(Identifier, id=token)
        .cte(ActiveRole, name="seed")
    )
    for depth in range(14):
        source, token = _shared_layer(source, token, LeftRole, RightRole, depth)

    compiled = sqlite.select(source).compile()

    assert_eq(compiled.sql.count(" AS (SELECT "), 15)
    assert_eq(compiled.params, (1,))
