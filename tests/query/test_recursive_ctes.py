"""Recursive definition construction through backend-owned query builders."""

from pydantic import BaseModel
from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.errors import QueryConstructionError


class Category[S = sqlite.Pending](sqlite.Model[S, "Category[sqlite.Fetched]"]):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent_id: sqlite.Col[int | None] = sqlite.Integer()


class Visit(BaseModel):
    id: int
    depth: int


class WalkRole:
    pass


@test(mark="fast")
def recursive_member_compiles_directly_with_anchor_first_parameters() -> None:
    """SQLite needs a direct recursive member, not a UNION derived table."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(7))
        .project(Visit, id=identifier, depth=depth)
    )

    walk = sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="walk",
        step=lambda previous: (
            sqlite.select(Category)
            .join(previous, on=Category.parent_id.eq_col(previous.column(identifier)))
            .where(previous.column(depth).lt(3))
            .project(Visit, id=Category.id, depth=previous.column(depth).add(1))
        ),
    )
    compiled = sqlite.select(walk).all().compile()

    assert_eq(compiled.sql.startswith('WITH RECURSIVE "walk" AS (SELECT '), True)
    assert_eq("UNION ALL SELECT " in compiled.sql, True)
    assert_eq("__snekql_union" in compiled.sql, False)
    assert_eq(compiled.params, (0, 7, 1, 3))


@test(mark="fast")
def recursive_member_requires_a_direct_self_source() -> None:
    """An ordinary UNION branch is not a recursive member."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor, WalkRole, name="walk", step=lambda _previous: anchor
        )


@test(mark="fast")
def recursive_member_rejects_distinct() -> None:
    """Recursive member restrictions apply before SQL compilation."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(previous)
                .all()
                .distinct()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            ),
        )


@test(mark="fast")
def recursive_self_cannot_be_on_a_nullable_join_side() -> None:
    """A constant projection must not hide a nullable recursive source."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(Category)
                .left_join(
                    previous, on=Category.parent_id.eq_col(previous.column(identifier))
                )
                .all()
                .project(Visit, id=Category.id, depth=sqlite.literal(1))
            ),
        )


@test(mark="fast")
def computed_anchor_does_not_claim_recursive_width() -> None:
    """Python int inference alone does not establish MariaDB anchor width."""
    identifier = Category.id.label("id")
    depth = Category.id.mul(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit,
                    id=previous.column(identifier),
                    depth=previous.column(depth).add(1),
                )
            ),
        )


@test(mark="fast")
def recursive_member_rejects_grouping() -> None:
    """A grouped self SELECT is not a supported recursive member."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
                .group_by(previous.column(identifier), previous.column(depth))
            ),
        )


@test(mark="fast")
def recursive_self_is_rejected_inside_a_member_subquery() -> None:
    """One direct self source must not authorize a second nested reference."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(previous)
                .where(sqlite.exists(sqlite.select(previous).all()))
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            ),
        )


class OptionalVisit(BaseModel):
    id: int | None
    depth: int


@test(mark="fast")
def recursive_member_rejects_aggregates_without_grouping() -> None:
    """Nullable compatible MIN outputs still cannot be recursive aggregates."""
    identifier = Category.parent_id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category).all().project(OptionalVisit, id=identifier, depth=depth)
    )

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    OptionalVisit,
                    id=previous.column(identifier).min(),
                    depth=previous.column(depth),
                )
            ),
        )


@test(mark="fast")
def completed_definition_does_not_publish_its_callback_self() -> None:
    """Only the returned relation can be consumed outside the callback."""
    captured: list[sqlite.Select[Visit]] = []
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    walk = sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="walk",
        step=lambda previous: (
            captured.append(sqlite.select(previous).all()),
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            ),
        )[1],
    )
    sqlite.select(walk).all().compile()
    sqlite.select(walk).all().compile()

    assert_eq(len(captured), 1)
    with assert_raises(sqlite.QueryCompilationError):
        captured[0].compile()


@test(mark="fast")
def incomplete_self_member_is_rejected_before_compilation() -> None:
    """Dynamic callbacks cannot bypass the explicit all()/where() requirement."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: sqlite.select(previous).project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            ),
        )


@test(mark="fast")
def failed_callback_does_not_publish_its_self_reference() -> None:
    """A saved query stays unusable after its factory rejects the member."""
    captured: list[sqlite.Select[Visit]] = []
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
            step=lambda previous: (
                captured.append(sqlite.select(previous).all()),
                anchor,
            )[1],
        )

    with assert_raises(sqlite.QueryCompilationError):
        captured[0].compile()
