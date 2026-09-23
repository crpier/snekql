"""Recursive callbacks preserve backend, named results and readiness."""

from typing import TYPE_CHECKING, assert_type

from snekql import mariadb, sqlite
from tests.query.test_recursive_ctes import Category, Visit, WalkRole
from tests.runtime.test_recursive_ctes import NativeCategory

if TYPE_CHECKING:
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).all().project(Visit, id=identifier, depth=depth)
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

    async def consume(transaction: sqlite.Transaction) -> None:
        assert_type(await transaction.fetch_all(sqlite.select(walk).all()), list[Visit])
        assert_type(
            await transaction.fetch_one_or_none(sqlite.select(walk).all()), Visit | None
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(walk.column(depth)).all()),
            list[int],
        )

    native = (
        mariadb.select(NativeCategory)
        .all()
        .project(Visit, id=NativeCategory.id, depth=mariadb.literal(0))
    )
    sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="wrong_backend",
        step=lambda _previous: native,  # ty: ignore[invalid-argument-type]
    )
    sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="incomplete",
        step=lambda _previous: sqlite.select(Category).project(  # ty: ignore[invalid-argument-type]
            Visit, id=Category.id, depth=sqlite.literal(0)
        ),
    )
    sqlite.recursive_cte(
        native,  # ty: ignore[invalid-argument-type]
        WalkRole,
        name="wrong_anchor",
        step=lambda _previous: anchor,
    )
