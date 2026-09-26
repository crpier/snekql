"""Recursive callbacks preserve backend, named results and readiness."""

from typing import TYPE_CHECKING, assert_type

from pydantic import BaseModel

from snekql import mariadb, sqlite
from tests.query.test_recursive_ctes import Category, OptionalVisit, Visit, WalkRole
from tests.runtime.test_recursive_ctes import NativeCategory

if TYPE_CHECKING:
    identifier = Category.id.label("id")
    depth = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Category).project(Visit, id=identifier, depth=depth)
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

    async def consume(transaction: sqlite.Transaction) -> None:
        assert_type(await transaction.fetch_all(sqlite.select(walk)), list[Visit])
        assert_type(
            await transaction.fetch_one_or_none(sqlite.select(walk)), Visit | None
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(walk.column(depth))),
            list[int],
        )

    native = mariadb.select(NativeCategory).project(
        Visit, id=NativeCategory.id, depth=mariadb.literal(0)
    )
    sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="wrong_backend",
    ).step(lambda _previous: native)  # ty: ignore[invalid-argument-type]
    sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="unfiltered",
    ).step(
        lambda _previous: sqlite.select(Category).project(
            Visit, id=Category.id, depth=sqlite.literal(0)
        )
    )
    sqlite.recursive_cte(
        anchor,
        WalkRole,
        name="unfiltered_self_member",
    ).step(
        lambda previous: sqlite.select(previous).project(
            Visit, id=previous.column(identifier), depth=previous.column(depth)
        )
    )
    sqlite.recursive_cte(
        native,  # ty: ignore[invalid-argument-type]
        WalkRole,
        name="wrong_anchor",
    ).step(lambda _previous: anchor)

    prepared = sqlite.recursive_cte(anchor, WalkRole, name="self_only")
    self_only = prepared.step(
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
    sqlite.select(prepared)  # ty: ignore[no-matching-overload]
    prepared.step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).eq("wrong"))  # ty: ignore[invalid-argument-type]
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )
    )
    prepared.step(
        lambda previous: (
            sqlite.select(previous)
            .where(Category.id.eq(1))  # ty: ignore[invalid-argument-type]
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )
    )
    sqlite.recursive_cte(
        sqlite.select(Category).project(Visit, id=identifier, depth=depth),
        WalkRole,
        name="unfiltered_anchor",
    )

    native_identifier = NativeCategory.id.label("id")
    native_depth = mariadb.literal(0).label("depth")
    native_anchor = mariadb.select(NativeCategory).project(
        Visit, id=native_identifier, depth=native_depth
    )
    native_prepared = mariadb.recursive_cte(native_anchor, WalkRole, name="self_only")
    native_self_only = native_prepared.step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(native_depth).lt(3))
            .project(
                Visit,
                id=previous.column(native_identifier),
                depth=previous.column(native_depth).add(1),
            )
        )
    )
    mariadb.select(native_prepared)  # ty: ignore[no-matching-overload]
    native_prepared.step(
        lambda previous: mariadb.select(previous).project(
            Visit,
            id=previous.column(native_identifier),
            depth=previous.column(native_depth),
        )
    )
    native_prepared.step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(native_depth).eq("wrong"))  # ty: ignore[invalid-argument-type]
            .project(
                Visit,
                id=previous.column(native_identifier),
                depth=previous.column(native_depth),
            )
        )
    )
    native_prepared.step(
        lambda previous: (
            mariadb.select(previous)
            .where(NativeCategory.id.eq(1))  # ty: ignore[invalid-argument-type]
            .project(
                Visit,
                id=previous.column(native_identifier),
                depth=previous.column(native_depth),
            )
        )
    )
    native_prepared.step(lambda _previous: anchor)  # ty: ignore[invalid-argument-type]
    mariadb.recursive_cte(anchor, WalkRole, name="wrong_anchor")  # ty: ignore[invalid-argument-type]
    mariadb.recursive_cte(
        mariadb.select(NativeCategory).project(
            Visit, id=native_identifier, depth=native_depth
        ),
        WalkRole,
        name="unfiltered_anchor",
    )

    async def consume_self_only(transaction: sqlite.Transaction) -> None:
        """A self-only member preserves the anchor's result and scalar types."""
        assert_type(await transaction.fetch_all(sqlite.select(self_only)), list[Visit])
        assert_type(
            await transaction.fetch_all(sqlite.select(self_only.column(identifier))),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(self_only.column(depth))),
            list[int],
        )
        await transaction.fetch_all(prepared)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(mariadb.select(native_self_only))  # ty: ignore[no-matching-overload]

    async def consume_native_self_only(transaction: mariadb.Transaction) -> None:
        """MariaDB self-only members retain their family and anchor domain."""
        assert_type(
            await transaction.fetch_all(mariadb.select(native_self_only)),
            list[Visit],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.select(native_self_only.column(native_identifier))
            ),
            list[int],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.select(native_self_only.column(native_depth))
            ),
            list[int],
        )
        await transaction.fetch_all(native_prepared)  # ty: ignore[no-matching-overload]
        await transaction.fetch_all(sqlite.select(self_only))  # ty: ignore[no-matching-overload]

    class OtherVisit(BaseModel):
        depth: int
        id: int

    class OtherRole:
        pass

    other = anchor.cte(OtherRole, name="other")
    prepared.step(
        lambda previous: (  # ty: ignore[invalid-argument-type]
            sqlite.select(previous).project(
                OtherVisit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )
    )
    prepared.step(
        lambda previous: (
            sqlite.select(previous)
            .where(other.column(depth).eq(0))  # ty: ignore[invalid-argument-type]
            .project(
                Visit, id=previous.column(identifier), depth=previous.column(depth)
            )
        )
    )
    native_other = native_anchor.cte(OtherRole, name="other")
    native_prepared.step(
        lambda previous: (  # ty: ignore[invalid-argument-type]
            mariadb.select(previous).project(
                OtherVisit,
                id=previous.column(native_identifier),
                depth=previous.column(native_depth),
            )
        )
    )
    native_prepared.step(
        lambda previous: (
            mariadb.select(previous)
            .where(native_other.column(native_depth).eq(0))  # ty: ignore[invalid-argument-type]
            .project(
                Visit,
                id=previous.column(native_identifier),
                depth=previous.column(native_depth),
            )
        )
    )

    optional_identifier = Category.parent_id.label("id")
    optional_anchor = sqlite.select(Category).project(
        OptionalVisit, id=optional_identifier, depth=depth
    )
    optional_walk = sqlite.recursive_cte(
        optional_anchor, WalkRole, name="optional_walk"
    ).step(
        lambda previous: (
            sqlite.select(previous)
            .where(previous.column(depth).lt(1))
            .project(
                OptionalVisit,
                id=previous.column(optional_identifier),
                depth=previous.column(depth).add(1),
            )
        )
    )
    native_optional_identifier = NativeCategory.parent_id.label("id")
    native_optional_anchor = mariadb.select(NativeCategory).project(
        OptionalVisit, id=native_optional_identifier, depth=native_depth
    )
    native_optional_walk = mariadb.recursive_cte(
        native_optional_anchor, WalkRole, name="optional_walk"
    ).step(
        lambda previous: (
            mariadb.select(previous)
            .where(previous.column(native_depth).lt(1))
            .project(
                OptionalVisit,
                id=previous.column(native_optional_identifier),
                depth=previous.column(native_depth).add(1),
            )
        )
    )

    async def consume_optional(transaction: sqlite.Transaction) -> None:
        """Staging does not erase nullable physical anchor outputs."""
        assert_type(
            await transaction.fetch_all(
                sqlite.select(optional_walk.column(optional_identifier))
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(sqlite.select(optional_walk.column(depth))),
            list[int],
        )

    async def consume_native_optional(transaction: mariadb.Transaction) -> None:
        """Native nullable anchors keep nonnullable literal outputs separate."""
        assert_type(
            await transaction.fetch_all(
                mariadb.select(native_optional_walk.column(native_optional_identifier))
            ),
            list[int | None],
        )
        assert_type(
            await transaction.fetch_all(
                mariadb.select(native_optional_walk.column(native_depth))
            ),
            list[int],
        )
