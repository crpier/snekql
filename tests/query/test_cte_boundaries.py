"""Definition scope and dependency failures stop at public compilation."""

from dataclasses import replace

from pydantic import BaseModel
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from tests.query.test_ctes import ActiveRole, FilteredRole, Identifier, Person
from tests.query.test_subqueries import Order, User


class OptionalIdentifier(BaseModel):
    """A scalar subquery may have no row."""

    id: int | None


@test(mark="fast")
def cte_definition_cannot_capture_its_consumers_row() -> None:
    """A consumer's FROM source is not an enclosing scope for a WITH body."""
    definition = (
        sqlite.select(Order)
        .where(Order.user_id.eq_col(User.id))
        .project(Identifier, id=Order.id)
        .cte(ActiveRole, name="correlated")
    )
    query = sqlite.select(User).where(sqlite.exists(sqlite.select(definition).all()))

    with assert_raises(sqlite.QueryCompilationError):
        query.compile()


@test(mark="fast")
def cte_definition_retains_its_own_nested_correlation() -> None:
    """A scalar subquery may reference the definition's own FROM row."""
    first_order = sqlite.scalar(
        sqlite.select(Order.id)
        .where(Order.user_id.eq_col(User.id))
        .order_by(Order.id.asc())
        .limit(1)
    )
    definition = (
        sqlite.select(User)
        .all()
        .project(OptionalIdentifier, id=first_order)
        .cte(ActiveRole, name="first_orders")
    )

    compiled = sqlite.select(definition).all().compile()

    assert_eq('"order"."user_id" = "user"."id"' in compiled.sql, True)
    assert_eq(compiled.params, (1,))


@test(mark="fast")
def nested_definition_cannot_shadow_a_reachable_with_name() -> None:
    """Distinct definitions share one case-insensitive WITH namespace."""
    identifier = Person.id.label("id")
    first = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=identifier)
        .cte(ActiveRole, name="shared")
    )
    second = (
        sqlite.select(first)
        .all()
        .project(Identifier, id=first.column(identifier))
        .cte(FilteredRole, name="SHARED")
    )

    with assert_raises(sqlite.QueryCompilationError):
        sqlite.select(second).all().compile()


@test(mark="fast")
def corrupted_cte_dependency_cycle_is_rejected_before_rendering() -> None:
    """Guard corrupted metadata even though public immutable builders form a DAG."""
    definition = (
        sqlite.select(Person)
        .all()
        .project(Identifier, id=Person.id)
        .cte(ActiveRole, name="cyclic")
    )
    relation = definition.__query_source__()
    original = relation.definition
    relation.definition = replace(
        original, state=replace(original.state, model=relation)
    )

    with assert_raises(sqlite.QueryCompilationError) as failure:
        sqlite.select(definition).all().compile()

    assert_eq(str(failure.exception), "CTE dependency cycle")
