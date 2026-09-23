"""Bounded recursive traversal through native database transactions."""

from collections.abc import AsyncGenerator
from typing import assert_type

from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_recursive_ctes import Category, Visit, WalkRole


class NativeCategory[S = mariadb.Pending](
    mariadb.Model[S, "NativeCategory[mariadb.Fetched]"]
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    parent_id: mariadb.Col[int | None] = mariadb.Integer()


@fixture
async def provide_categories() -> AsyncGenerator[sqlite.Database]:
    """A three-node cycle with a leaf demonstrates repeated visits and branching."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_categories": sqlite.scaffold([Category])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert(
                    [
                        Category(id=1, parent_id=3),
                        Category(id=2, parent_id=1),
                        Category(id=3, parent_id=2),
                        Category(id=4, parent_id=1),
                    ]
                )
            )
        yield database


@fixture
async def provide_native_categories() -> AsyncGenerator[mariadb.Database]:
    """Use the same cycle against MariaDB's recursive type rules."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_categories": mariadb.scaffold([NativeCategory])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(
                    [
                        NativeCategory(id=1, parent_id=3),
                        NativeCategory(id=2, parent_id=1),
                        NativeCategory(id=3, parent_id=2),
                        NativeCategory(id=4, parent_id=1),
                    ]
                )
            )
        yield database


_TRAVERSALS = [
    Param((1, 0, [(1, 0)]), name="depth_zero"),
    Param((99, 3, []), name="missing_root"),
    Param((1, 3, [(1, 0), (2, 1), (4, 1), (3, 2), (1, 3)]), name="bounded_revisits"),
]


@test(_TRAVERSALS, mark="medium")
async def sqlite_recursive_traversal(
    case: tuple[int, int, list[tuple[int, int]]],
) -> None:
    """Depth bounds stop revisits; final ordering is independent of evaluation."""
    database = await load_fixture(provide_categories())
    root, budget, expected = case
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(root))
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
            .where(previous.column(depth).lt(budget))
            .project(Visit, id=Category.id, depth=previous.column(depth).add(1))
        )
    )
    query = (
        sqlite.select(walk)
        .all()
        .order_by(walk.column(depth).asc(), walk.column(identifier).asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[Visit])
    assert_eq([(row.id, row.depth) for row in rows], expected)


@test(_TRAVERSALS, mark="slow")
async def mariadb_recursive_traversal(
    case: tuple[int, int, list[tuple[int, int]]],
) -> None:
    """Native recursive members preserve the literal's signed integer domain."""
    database = await load_fixture(provide_native_categories())
    root, budget, expected = case
    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(root))
        .project(Visit, id=identifier, depth=depth)
    )
    walk = mariadb.recursive_cte(
        anchor,
        WalkRole,
        name="walk",
    ).step(
        lambda previous: (
            mariadb.select(NativeCategory)
            .join(
                previous,
                on=NativeCategory.parent_id.eq_col(previous.column(identifier)),
            )
            .where(previous.column(depth).lt(budget))
            .project(Visit, id=NativeCategory.id, depth=previous.column(depth).add(1))
        )
    )
    query = (
        mariadb.select(walk)
        .all()
        .order_by(walk.column(depth).asc(), walk.column(identifier).asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[Visit])
    assert_eq([(row.id, row.depth) for row in rows], expected)


@test(mark="medium")
async def prepared_recursion_cannot_be_executed() -> None:
    """A dynamic caller cannot fetch an unfinished recursive builder."""
    database = await load_fixture(provide_categories())
    anchor = (
        sqlite.select(Category)
        .all()
        .project(Visit, id=Category.id, depth=sqlite.literal(0))
    )
    prepared = sqlite.recursive_cte(anchor, WalkRole, name="walk")

    async with database.transaction() as transaction:
        with assert_raises(sqlite.QueryCompilationError):
            await transaction.fetch_all(prepared)  # ty: ignore[no-matching-overload]


@test(mark="medium")
async def sqlite_recursive_self_only_member() -> None:
    """A self-only member preserves the identifier while incrementing depth."""
    database = await load_fixture(provide_categories())
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(1))
        .project(Visit, id=identifier, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(3))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(walk).all().order_by(walk.column(depth).asc())
        )

    assert_type(rows, list[Visit])
    assert_eq([(row.id, row.depth) for row in rows], [(1, 0), (1, 1), (1, 2), (1, 3)])


@test(mark="slow")
async def mariadb_recursive_self_only_member() -> None:
    """A self-only member preserves the identifier while incrementing depth."""
    database = await load_fixture(provide_native_categories())
    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(1))
        .project(Visit, id=identifier, depth=depth)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(depth).lt(3))
            .project(
                Visit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(walk).all().order_by(walk.column(depth).asc())
        )

    assert_type(rows, list[Visit])
    assert_eq([(row.id, row.depth) for row in rows], [(1, 0), (1, 1), (1, 2), (1, 3)])
