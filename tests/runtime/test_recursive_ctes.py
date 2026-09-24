"""Bounded recursive traversal through native database transactions."""

from collections.abc import AsyncGenerator
from typing import Literal, assert_type
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_recursive_ctes import Category, Visit, WalkRole
from tests.runtime.test_named_codecs import (
    LocalDocument,
    MariaDocument,
    provide_mariadb_documents,
    provide_sqlite_documents,
)


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
    """Depth budgets bound repeated visits; final order is independent of evaluation."""
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


class DocumentVisit(BaseModel):
    depth: int
    key: UUID
    values: list[int]


@test(mark="medium")
async def sqlite_recursive_outputs_preserve_logical_codecs() -> None:
    """Unchanged UUID/JSON fields decode after recursion and reference renaming."""
    database = await load_fixture(provide_sqlite_documents())
    key = LocalDocument.id.label("key")
    depth = sqlite.literal(0).label("depth")
    values = LocalDocument.payload.label("values")
    anchor = (
        sqlite.select(LocalDocument)
        .all()
        .project(DocumentVisit, values=values, key=key, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                DocumentVisit,
                depth=previous.column(depth).add(1),
                key=previous.column(key),
                values=previous.column(values),
            )
        )
    )

    class ReadRole:
        pass

    renamed = sqlite.alias(walk, ReadRole, name="renamed")

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(renamed)
            .where(renamed.column(key).eq(UUID(int=1)))
            .order_by(renamed.column(depth).asc())
        )

    assert_eq(
        rows,
        [
            DocumentVisit(depth=0, key=UUID(int=1), values=[2, 3]),
            DocumentVisit(depth=1, key=UUID(int=1), values=[2, 3]),
        ],
    )


@test(mark="slow")
async def mariadb_recursive_outputs_preserve_logical_codecs() -> None:
    """Unchanged UUID/JSON fields decode after recursion and reference renaming."""
    database = await load_fixture(provide_mariadb_documents())
    key = MariaDocument.id.label("key")
    depth = mariadb.literal(0).label("depth")
    values = MariaDocument.payload.label("values")
    anchor = (
        mariadb.select(MariaDocument)
        .all()
        .project(DocumentVisit, values=values, key=key, depth=depth)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                DocumentVisit,
                depth=previous.column(depth).add(1),
                key=previous.column(key),
                values=previous.column(values),
            )
        )
    )

    class ReadRole:
        pass

    renamed = mariadb.alias(walk, ReadRole, name="renamed")

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(renamed)
            .where(renamed.column(key).eq(UUID(int=1)))
            .order_by(renamed.column(depth).asc())
        )

    assert_eq(
        rows,
        [
            DocumentVisit(depth=0, key=UUID(int=1), values=[2, 3]),
            DocumentVisit(depth=1, key=UUID(int=1), values=[2, 3]),
        ],
    )


@test(
    [Param(True, name="validate"), Param(False, name="without_source_validation")],
    mark="medium",
)
async def sqlite_recursion_validates_only_final_rows(
    validate: Literal[True, False],
) -> None:
    """An invalid intermediate depth is filtered by SQL before Python validation."""
    database = await load_fixture(provide_categories())

    class FinalVisit(BaseModel):
        depth: int = Field(gt=0)
        id: int

        @field_validator("id")
        @classmethod
        def increment(cls, identifier: int) -> int:
            return identifier + 10

    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(1))
        .project(FinalVisit, id=identifier, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                FinalVisit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(walk)
            .where(walk.column(depth).gt(0))
            .order_by(walk.column(depth).asc()),
            validate=validate,
        )

    assert_eq(
        rows,
        [
            FinalVisit.model_construct(id=11, depth=1),
            FinalVisit.model_construct(id=11, depth=2),
        ],
    )


@test(
    [Param(True, name="validate"), Param(False, name="without_source_validation")],
    mark="slow",
)
async def mariadb_recursion_validates_only_final_rows(
    validate: Literal[True, False],
) -> None:
    """An invalid intermediate depth is filtered by SQL before Python validation."""
    database = await load_fixture(provide_native_categories())

    class FinalVisit(BaseModel):
        depth: int = Field(gt=0)
        id: int

        @field_validator("id")
        @classmethod
        def increment(cls, identifier: int) -> int:
            return identifier + 10

    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(1))
        .project(FinalVisit, id=identifier, depth=depth)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(depth).lt(2))
            .project(
                FinalVisit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(walk)
            .where(walk.column(depth).gt(0))
            .order_by(walk.column(depth).asc()),
            validate=validate,
        )

    assert_eq(
        rows,
        [
            FinalVisit.model_construct(id=11, depth=1),
            FinalVisit.model_construct(id=11, depth=2),
        ],
    )


@test(
    [Param(True, name="validate"), Param(False, name="without_source_validation")],
    mark="medium",
)
async def sqlite_recursive_final_contract_is_strict(
    validate: Literal[True, False],
) -> None:
    """Before validators cannot smuggle coercible strings into integer fields."""
    database = await load_fixture(provide_categories())

    class StrictVisit(BaseModel):
        depth: int
        id: int

        @field_validator("id", mode="before")
        @classmethod
        def stringify(cls, identifier: int) -> str:
            return str(identifier)

    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(1))
        .project(StrictVisit, id=identifier, depth=depth)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                StrictVisit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_all(sqlite.select(walk).all(), validate=validate)


@test(
    [Param(True, name="validate"), Param(False, name="without_source_validation")],
    mark="slow",
)
async def mariadb_recursive_final_contract_is_strict(
    validate: Literal[True, False],
) -> None:
    """Before validators cannot smuggle coercible strings into integer fields."""
    database = await load_fixture(provide_native_categories())

    class StrictVisit(BaseModel):
        depth: int
        id: int

        @field_validator("id", mode="before")
        @classmethod
        def stringify(cls, identifier: int) -> str:
            return str(identifier)

    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(0).label("depth")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(1))
        .project(StrictVisit, id=identifier, depth=depth)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                StrictVisit,
                id=previous.column(identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )

    async with database.transaction() as transaction:
        with assert_raises(mariadb.ModelValidationError):
            await transaction.fetch_all(mariadb.select(walk).all(), validate=validate)


@test(mark="medium")
async def sqlite_recursive_presence_distinguishes_null_member() -> None:
    """An all-NULL recursive member is a present row, not an absent outer join."""
    database = await load_fixture(provide_categories())

    class NullVisit(BaseModel):
        id: int | None

    class MissingRole:
        pass

    missing = sqlite.alias(Category, MissingRole, name="missing")
    identifier = Category.parent_id.label("id")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(2))
        .project(NullVisit, id=identifier)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(Category)
            .join(previous, on=Category.id.eq(2))
            .left_join(missing, on=Category.id.eq(99))
            .where(previous.column(identifier).is_not_null())
            .project(NullVisit, id=missing.column(Category.parent_id))
        )
    )
    query = (
        sqlite.select(Category)
        .left_join(walk, on=Category.id.eq(1) & walk.column(identifier).is_null())
        .all()
        .order_by(Category.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq([row[1] for row in rows], [NullVisit(id=None), None, None, None])


@test(mark="slow")
async def mariadb_recursive_presence_distinguishes_null_member() -> None:
    """An all-NULL recursive member is a present row, not an absent outer join."""
    database = await load_fixture(provide_native_categories())

    class NullVisit(BaseModel):
        id: int | None

    class MissingRole:
        pass

    missing = mariadb.alias(NativeCategory, MissingRole, name="missing")
    identifier = NativeCategory.parent_id.label("id")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(2))
        .project(NullVisit, id=identifier)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(NativeCategory)
            .join(previous, on=NativeCategory.id.eq(2))
            .left_join(missing, on=NativeCategory.id.eq(99))
            .where(previous.column(identifier).is_not_null())
            .project(NullVisit, id=missing.column(NativeCategory.parent_id))
        )
    )
    query = (
        mariadb.select(NativeCategory)
        .left_join(walk, on=NativeCategory.id.eq(1) & walk.column(identifier).is_null())
        .all()
        .order_by(NativeCategory.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_eq([row[1] for row in rows], [NullVisit(id=None), None, None, None])


_INTEGER_BOUNDARIES = [
    Param((0, 2147483648, [0, 2147483648]), name="above_signed_32"),
    Param((0, -2147483649, [-2147483649, 0]), name="below_signed_32"),
    Param(
        (9223372036854775806, 1, [9223372036854775806, 9223372036854775807]),
        name="signed_64_max",
    ),
    Param(
        (-9223372036854775808, 1, [-9223372036854775808, -9223372036854775807]),
        name="signed_64_min",
    ),
]
"""Two-row recursions exercise width without relying on iteration limits."""


@test(_INTEGER_BOUNDARIES, mark="medium")
async def sqlite_recursive_literal_retains_signed_width(
    case: tuple[int, int, list[int]],
) -> None:
    """A renamed direct self source preserves the anchor's full signed domain."""
    database = await load_fixture(provide_categories())
    start, increment, expected = case

    class MemberRole:
        pass

    identifier = Category.id.label("id")
    depth = sqlite.literal(start).label("depth")
    anchor = (
        sqlite.select(Category)
        .where(Category.id.eq(1))
        .project(Visit, depth=depth, id=identifier)
    )
    walk = sqlite.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            sqlite.select(member := sqlite.alias(previous, MemberRole, name="member"))
            .where(member.column(depth).eq(start))
            .project(
                Visit,
                depth=member.column(depth).add(increment),
                id=member.column(identifier),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(walk).all().order_by(walk.column(depth).asc())
        )

    assert_eq([row.depth for row in rows], expected)


@test(_INTEGER_BOUNDARIES, mark="slow")
async def mariadb_recursive_literal_retains_signed_width(
    case: tuple[int, int, list[int]],
) -> None:
    """A renamed direct self source preserves the anchor's full signed domain."""
    database = await load_fixture(provide_native_categories())
    start, increment, expected = case

    class MemberRole:
        pass

    identifier = NativeCategory.id.label("id")
    depth = mariadb.literal(start).label("depth")
    anchor = (
        mariadb.select(NativeCategory)
        .where(NativeCategory.id.eq(1))
        .project(Visit, depth=depth, id=identifier)
    )
    walk = mariadb.recursive_cte(anchor, WalkRole, name="walk").step(
        lambda previous: (
            mariadb.select(member := mariadb.alias(previous, MemberRole, name="member"))
            .where(member.column(depth).eq(start))
            .project(
                Visit,
                depth=member.column(depth).add(increment),
                id=member.column(identifier),
            )
        )
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(walk).all().order_by(walk.column(depth).asc())
        )

    assert_eq([row.depth for row in rows], expected)
