"""Public named helper annotations preserve composition contracts."""

from typing import TYPE_CHECKING, Any, assert_type

from pydantic import BaseModel

from snekql import mariadb, sqlite
from tests.query.test_cte_annotations import NativeCategory
from tests.query.test_recursive_ctes import (
    OptionalVisit,
    PeerRole,
    Visit,
    WalkRole,
)


class NativeDetail[S = mariadb.Pending](
    mariadb.Model[S, "NativeDetail[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


class OtherVisit(BaseModel):
    depth: int
    id: int


if TYPE_CHECKING:
    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory).all().project(Visit, id=identifier, depth=depth)
    )

    def advance(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    def relation() -> mariadb.Cte[NativeCategory, Visit, WalkRole]:
        return mariadb.recursive_cte(anchor, WalkRole, name="walk").step(advance)

    def branch() -> mariadb.NamedOperand[Visit]:
        return anchor

    walk = relation()
    combined = anchor.union_all(branch())

    async def consume(transaction: mariadb.Transaction) -> None:
        assert_type(
            await transaction.fetch_all(mariadb.select(walk).all()), list[Visit]
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(walk.column(identifier)).all()),
            list[int],
        )
        assert_type(await transaction.fetch_all(combined), list[Visit])
        await transaction.fetch_all(branch())  # ty: ignore[no-matching-overload]

    branch().where(NativeCategory.id.eq(1))  # ty: ignore[unresolved-attribute]

    def incomplete(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return mariadb.select(previous).project(
            Visit, id=previous.column(identifier), depth=previous.column(depth)
        )  # ty: ignore[invalid-return-type]

    def unnamed(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return mariadb.select(previous).all()  # ty: ignore[invalid-return-type]

    def wrong_comparison(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).eq("wrong"))  # ty: ignore[invalid-argument-type]
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def unjoined_scope(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        mariadb.select(previous).where(NativeCategory.id.eq(1))  # ty: ignore[invalid-argument-type]
        return (
            mariadb.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def wrong_family(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            mariadb.select(previous)  # ty: ignore[invalid-return-type]
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def different_role(
        previous: mariadb.Cte[NativeCategory, Visit, PeerRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def different_result(
        previous: mariadb.Cte[NativeCategory, Visit, WalkRole],
    ) -> mariadb.NamedOperand[OtherVisit]:
        return (
            mariadb.select(previous)
            .all()
            .project(
                OtherVisit,
                id=previous.column(identifier),
                depth=previous.column(depth),
            )
        )

    prepared = mariadb.recursive_cte(anchor, WalkRole, name="walk")
    prepared.step(different_role)  # ty: ignore[invalid-argument-type]
    prepared.step(different_result)  # ty: ignore[invalid-argument-type]
    sqlite.select(walk)  # ty: ignore[no-matching-overload]

    optional_id = NativeDetail.id.label("id")
    optional_anchor = (
        mariadb.select(NativeCategory)
        .left_join(NativeDetail, on=NativeCategory.id.eq_col(NativeDetail.id))
        .all()
        .project(OptionalVisit, id=optional_id, depth=depth)
    )

    def nullable_member(
        previous: mariadb.Cte[
            NativeCategory | NativeDetail, OptionalVisit, WalkRole, NativeCategory
        ],
    ) -> mariadb.NamedOperand[OptionalVisit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                OptionalVisit,
                id=previous.column(optional_id),
                depth=previous.column(depth).add(1),
            )
        )

    optional_walk = mariadb.recursive_cte(
        optional_anchor, WalkRole, name="optional_walk"
    ).step(nullable_member)

    async def consume_nullable(
        transaction: mariadb.Transaction,
        previous: mariadb.Cte[
            NativeCategory | NativeDetail, OptionalVisit, WalkRole, NativeCategory
        ],
    ) -> None:
        assert_type(
            await transaction.fetch_all(
                mariadb.select(previous.column(optional_id)).all()
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(previous.column(depth)).all()),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(optional_walk).all()),
            list[OptionalVisit],
        )

    def wrong_nullability(
        previous: mariadb.Cte[NativeCategory | NativeDetail, OptionalVisit, WalkRole],
    ) -> mariadb.NamedOperand[OptionalVisit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                OptionalVisit,
                id=previous.column(optional_id),
                depth=previous.column(depth).add(1),
            )
        )

    mariadb.recursive_cte(optional_anchor, WalkRole, name="bad").step(
        wrong_nullability  # ty: ignore[invalid-argument-type]
    )

    def different_source(
        previous: mariadb.Cte[NativeDetail, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    prepared.step(different_source)  # ty: ignore[invalid-argument-type]

    def generic_advance[SourceT: mariadb.Model[Any, Any]](
        previous: mariadb.Cte[SourceT, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    generic_walk = prepared.step(generic_advance)

    def alias_helper() -> mariadb.Cte[NativeCategory, Visit, PeerRole]:
        return mariadb.alias(walk, PeerRole, name="peer")

    async def consume_helper(transaction: mariadb.Transaction) -> None:
        assert_type(
            await transaction.fetch_all(mariadb.select(generic_walk).all()), list[Visit]
        )
        assert_type(
            await transaction.fetch_all(mariadb.select(alias_helper()).all()),
            list[Visit],
        )
