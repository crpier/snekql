"""Recursive definition construction through backend-owned query builders."""

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql.errors import QueryConstructionError


class Category[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Category[sqlite.Row]]]
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
    ).step(
        lambda previous: (
            sqlite.select(Category)
            .join(previous, on=Category.parent_id.eq_col(previous.column(identifier)))
            .where(previous.column(depth).lt(3))
            .project(Visit, id=Category.id, depth=previous.column(depth).add(1))
        )
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
            anchor,
            WalkRole,
            name="walk",
        ).step(lambda _previous: anchor)


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
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .distinct()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
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
        ).step(
            lambda previous: (
                sqlite.select(Category)
                .left_join(
                    previous, on=Category.parent_id.eq_col(previous.column(identifier))
                )
                .all()
                .project(Visit, id=Category.id, depth=sqlite.literal(1))
            )
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
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit,
                    id=previous.column(identifier),
                    depth=previous.column(depth).add(1),
                )
            )
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
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
                .group_by(previous.column(identifier), previous.column(depth))
            )
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
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .where(sqlite.exists(sqlite.select(previous).all()))
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
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
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    OptionalVisit,
                    id=previous.column(identifier).min(),
                    depth=previous.column(depth),
                )
            )
        )


@test(mark="fast")
def completed_definition_does_not_publish_its_callback_self() -> None:
    """Only the returned relation can be consumed outside the callback."""
    captured: list[Callable[[], sqlite.CompiledQuery]] = []
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    walk = sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="walk",
    ).step(
        lambda previous: (
            captured.append(sqlite.select(previous).all().compile),
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            ),
        )[1]
    )
    sqlite.select(walk).all().compile()
    sqlite.select(walk).all().compile()

    assert_eq(len(captured), 1)
    with assert_raises(sqlite.QueryCompilationError):
        captured[0]()


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
        ).step(
            lambda previous: sqlite.select(previous).project(  # ty: ignore[invalid-argument-type]
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )


@test(mark="fast")
def failed_callback_does_not_publish_its_self_reference() -> None:
    """A saved query stays unusable after its factory rejects the member."""
    captured: list[Callable[[], sqlite.CompiledQuery]] = []
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError):
        sqlite.recursive_cte(
            anchor,
            WalkRole,
            name="walk",
        ).step(
            lambda previous: (
                captured.append(sqlite.select(previous).all().compile),
                anchor,
            )[1]
        )

    with assert_raises(sqlite.QueryCompilationError):
        captured[0]()


@test(mark="fast")
def prepared_recursion_is_not_a_query_source() -> None:
    """A prepared anchor exposes no recursive relation before step validation."""
    anchor = (
        sqlite.select(Category)
        .all()
        .project(Visit, id=Category.id, depth=sqlite.literal(0))
    )
    prepared = sqlite.recursive_cte(anchor, WalkRole, name="walk")

    with assert_raises(QueryConstructionError):
        sqlite.select(prepared)  # ty: ignore[no-matching-overload]


@test(mark="fast")
def failed_step_does_not_poison_prepared_anchor() -> None:
    """The same immutable preparation can construct a valid fresh definition."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)
    prepared = sqlite.recursive_cte(anchor, WalkRole, name="walk")
    with assert_raises(QueryConstructionError):
        prepared.step(lambda _previous: anchor)

    walk = prepared.step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )
    compiled = sqlite.select(walk).all().compile()

    assert_eq(compiled.params, (0, 1, 1))


class PeerRole:
    pass


@test(mark="fast")
def recursive_member_rejects_multiple_aliased_self_sources() -> None:
    """Renaming self does not permit a second recursive source."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(previous)
                .join(
                    peer := sqlite.alias(previous, PeerRole, name="peer"),
                    on=previous.column(identifier).eq_col(peer.column(identifier)),
                )
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
        )

    assert_eq(
        str(rejected.exception), "recursive member requires one direct self source"
    )


@test(mark="fast")
def recursive_member_rejects_indirect_self_dependency() -> None:
    """A direct source does not authorize self inside a dependent definition."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(previous)
                .where(
                    sqlite.exists(
                        sqlite.select(
                            sqlite.select(previous)
                            .all()
                            .project(
                                Visit,
                                id=previous.column(identifier),
                                depth=previous.column(depth),
                            )
                            .cte(PeerRole, name="indirect")
                        ).all()
                    )
                )
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
        )

    assert_eq(
        str(rejected.exception), "recursive self reference escaped its direct member"
    )


@test(mark="fast")
def escaped_self_cannot_become_another_recursive_anchor() -> None:
    """A saved named self query never establishes a new legal anchor scope."""
    captured: list[object] = []
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)
    sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            captured.append(
                sqlite.select(Category)
                .join(previous, on=Category.id.eq_col(previous.column(identifier)))
                .all()
                .project(Visit, id=identifier, depth=depth)
            ),
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            ),
        )[1]
    )

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(
            captured[0],  # ty: ignore[invalid-argument-type]
            PeerRole,
            name="other",
        ).step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
        )

    assert_eq(
        str(rejected.exception), "recursive self reference escaped its direct member"
    )


@test(
    [
        Param("order", name="order"),
        Param("limit", name="limit"),
        Param("offset", name="offset"),
    ],
    mark="fast",
)
def recursive_member_rejects_local_bounds(clause: str) -> None:
    """Local bounds must not reach recursive SQL, even with a complete member."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                member := sqlite.select(previous)
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                ),
                {
                    "order": lambda: member.order_by(previous.column(depth).asc()),
                    "limit": lambda: member.limit(1),
                    "offset": lambda: member.offset(1),
                }[clause](),
            )[1]
        )

    assert_eq(
        str(rejected.exception),
        "UNION operands cannot have local ordering or pagination; use a CTE",
    )


@test(mark="fast")
def recursive_member_cannot_widen_anchor_nullability() -> None:
    """A nullable final field does not weaken the anchor's nonnullable contract."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category).all().project(OptionalVisit, id=identifier, depth=depth)
    )

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(Category)
                .join(previous, on=Category.id.eq_col(previous.column(identifier)))
                .all()
                .project(
                    OptionalVisit, id=Category.parent_id, depth=previous.column(depth)
                )
            )
        )

    assert_eq(
        str(rejected.exception),
        "UNION right output cannot widen the left output's nullability",
    )


@test(mark="fast")
def recursive_member_cannot_change_anchor_codec() -> None:
    """The same logical int in TEXT is not the anchor's INTEGER wire contract."""

    class TextIdentifier[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[TextIdentifier[sqlite.Row]]]
        id: sqlite.Col[int] = sqlite.Text()

    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(TextIdentifier)
                .join(
                    previous, on=TextIdentifier.id.eq_col(previous.column(identifier))
                )
                .all()
                .project(Visit, id=TextIdentifier.id, depth=previous.column(depth))
            )
        )

    assert_eq(
        str(rejected.exception),
        "UNION requires compatible logical domains, wire encodings and decode policies",
    )


@test(mark="fast")
def nested_recursion_cannot_capture_outer_self_in_its_anchor() -> None:
    """An inner recursive definition cannot depend on its unfinished outer one."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(previous)
                .where(
                    sqlite.exists(
                        sqlite.select(
                            sqlite.recursive_cte(
                                sqlite.select(Category)
                                .join(
                                    previous,
                                    on=Category.id.eq_col(previous.column(identifier)),
                                )
                                .all()
                                .project(Visit, id=identifier, depth=depth),
                                PeerRole,
                                name="inner_walk",
                            ).step(
                                lambda inner: (
                                    sqlite.select(inner)
                                    .all()
                                    .project(
                                        Visit,
                                        id=inner.column(identifier),
                                        depth=inner.column(depth),
                                    )
                                )
                            )
                        ).all()
                    )
                )
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
            )
        )

    assert_eq(
        str(rejected.exception), "recursive self reference escaped its direct member"
    )


@test(mark="fast")
def recursive_member_cannot_widen_native_text_capacity() -> None:
    """Matching Python str types do not prove equal MariaDB SQL capacities."""

    class Narrow[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Narrow[mariadb.Row]]]
        value: mariadb.Col[str] = mariadb.Text(length=4)

    class Wide[S = mariadb.Pending](mariadb.Model[S]):
        __row_type__: ClassVar[mariadb.ReadType[Wide[mariadb.Row]]]
        value: mariadb.Col[str] = mariadb.Text(length=8)

    class TextVisit(BaseModel):
        value: str

    anchor = (
        mariadb.select(Narrow)
        .all()
        .project(TextVisit, value=Narrow.value.label("value"))
    )

    with assert_raises(QueryConstructionError) as rejected:
        mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                mariadb.select(Wide)
                .join(previous, on=Wide.value.eq("seed"))
                .all()
                .project(TextVisit, value=Wide.value)
            )
        )

    assert_eq(
        str(rejected.exception),
        "UNION requires compatible logical domains, wire encodings and decode policies",
    )


@test(mark="fast")
def recursive_member_rejects_locking_select() -> None:
    """Locks cannot be hidden inside an otherwise complete recursive member."""
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    with assert_raises(QueryConstructionError) as rejected:
        sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
            lambda previous: (
                sqlite.select(previous)
                .all()
                .project(
                    Visit, id=previous.column(identifier), depth=previous.column(depth)
                )
                .for_update()
            )
        )

    assert_eq(str(rejected.exception), "UNION operands cannot contain a locking SELECT")
