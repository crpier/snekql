"""Public named helper annotations preserve composition contracts."""

from typing import TYPE_CHECKING, Any, ClassVar, assert_type

from pydantic import BaseModel

from snekql import mariadb, sqlite
from tests.query.test_recursive_ctes import (
    Category,
    OptionalVisit,
    PeerRole,
    Visit,
    WalkRole,
)


class Detail[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Detail[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class OtherVisit(BaseModel):
    depth: int
    id: int


if TYPE_CHECKING:
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)

    def advance(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    def relation() -> sqlite.Cte[Category, Visit, WalkRole]:
        return sqlite.recursive_cte(anchor, WalkRole, name="walk").step(advance)

    def branch() -> sqlite.NamedOperand[Visit]:
        return anchor

    walk = relation()
    combined = anchor.union_all(branch())

    async def consume(transaction: sqlite.Transaction) -> None:
        assert_type(await transaction.fetch_all(sqlite.select(walk).all()), list[Visit])
        assert_type(
            await transaction.fetch_all(sqlite.select(walk.column(identifier)).all()),
            list[int],
        )
        assert_type(await transaction.fetch_all(combined), list[Visit])
        await transaction.fetch_all(branch())  # ty: ignore[no-matching-overload]

    branch().where(Category.id.eq(1))  # ty: ignore[unresolved-attribute]

    def unfiltered(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return sqlite.select(previous).project(
            Visit, id=previous.column(identifier), depth=previous.column(depth)
        )

    def unnamed(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return sqlite.select(previous).all()  # ty: ignore[invalid-return-type]

    def wrong_comparison(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).eq("wrong"))  # ty: ignore[invalid-argument-type]
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def unjoined_scope(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        sqlite.select(previous).where(Category.id.eq(1))  # ty: ignore[invalid-argument-type]
        return (
            sqlite.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def wrong_family(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> mariadb.NamedOperand[Visit]:
        return (
            sqlite.select(previous)  # ty: ignore[invalid-return-type]
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def different_role(
        previous: sqlite.Cte[Category, Visit, PeerRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    def different_result(
        previous: sqlite.Cte[Category, Visit, WalkRole],
    ) -> sqlite.NamedOperand[OtherVisit]:
        return (
            sqlite.select(previous)
            .all()
            .project(
                OtherVisit,
                id=previous.column(identifier),
                depth=previous.column(depth),
            )
        )

    prepared = sqlite.recursive_cte(anchor, WalkRole, name="walk")
    prepared.step(different_role)  # ty: ignore[invalid-argument-type]
    prepared.step(different_result)  # ty: ignore[invalid-argument-type]
    mariadb.select(walk)  # ty: ignore[no-matching-overload]

    optional_id = Detail.id.label("id")
    optional_anchor = (
        sqlite.select(Category)
        .left_join(Detail, on=Category.id.eq_col(Detail.id))
        .all()
        .project(OptionalVisit, id=optional_id, depth=depth)
    )

    def nullable_member(
        previous: sqlite.Cte[Category | Detail, OptionalVisit, WalkRole, Category],
    ) -> sqlite.NamedOperand[OptionalVisit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                OptionalVisit,
                id=previous.column(optional_id),
                depth=previous.column(depth).add(1),
            )
        )

    optional_walk = sqlite.recursive_cte(
        optional_anchor, WalkRole, name="optional_walk"
    ).step(nullable_member)

    async def consume_nullable(
        transaction: sqlite.Transaction,
        previous: sqlite.Cte[Category | Detail, OptionalVisit, WalkRole, Category],
    ) -> None:
        assert_type(
            await transaction.fetch_all(
                sqlite.select(previous.column(optional_id)).all()
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(previous.column(depth)).all()),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(optional_walk).all()),
            list[OptionalVisit],
        )

    def wrong_nullability(
        previous: sqlite.Cte[Category | Detail, OptionalVisit, WalkRole],
    ) -> sqlite.NamedOperand[OptionalVisit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                OptionalVisit,
                id=previous.column(optional_id),
                depth=previous.column(depth).add(1),
            )
        )

    sqlite.recursive_cte(optional_anchor, WalkRole, name="bad").step(
        wrong_nullability  # ty: ignore[invalid-argument-type]
    )

    def different_source(
        previous: sqlite.Cte[Detail, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .all()
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )

    prepared.step(different_source)  # ty: ignore[invalid-argument-type]

    def generic_advance[SourceT: sqlite.Model[Any]](
        previous: sqlite.Cte[SourceT, Visit, WalkRole],
    ) -> sqlite.NamedOperand[Visit]:
        return (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )

    generic_walk = prepared.step(generic_advance)

    def alias_helper() -> sqlite.Cte[Category, Visit, PeerRole]:
        return sqlite.alias(walk, PeerRole, name="peer")

    async def consume_helper(transaction: sqlite.Transaction) -> None:
        assert_type(
            await transaction.fetch_all(sqlite.select(generic_walk).all()), list[Visit]
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(alias_helper()).all()),
            list[Visit],
        )
