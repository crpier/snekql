"""Owner-free native literals through named projection compilation."""

from typing import ClassVar

from pydantic import BaseModel
from snektest import Param, assert_eq, assert_raises, test

from snekql import mariadb, sqlite


class Source[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Source[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class Depth(BaseModel):
    depth: int


@test(mark="fast")
def integer_literal_is_bound_without_claiming_a_table_owner() -> None:
    """A depth seed has an integer domain without borrowing a source column."""
    query = sqlite.select(Source).project(Depth, depth=sqlite.literal(0).label("depth"))

    compiled = query.compile()

    assert_eq(compiled.sql, 'SELECT ? AS "depth" FROM "source"')
    assert_eq(compiled.params, (0,))


class NativeSource[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[NativeSource[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


@test(mark="fast")
def mariadb_integer_literal_establishes_signed_64_width() -> None:
    """A small constant must not narrow a future recursive anchor to INT32."""
    query = mariadb.select(NativeSource).project(
        Depth, depth=mariadb.literal(0).label("depth")
    )

    compiled = query.compile()

    assert_eq(
        compiled.sql,
        "SELECT CAST(CAST(%s AS DECIMAL(19, 0)) AS SIGNED) AS `depth` FROM `native_source`",
    )
    assert_eq(compiled.params, (0,))


class SeedRole:
    pass


@test(mark="fast")
def integer_literal_retains_native_arithmetic_across_a_cte() -> None:
    """A literal anchor must compose with the computed next depth's wire policy."""
    token = sqlite.literal(0).label("depth")
    anchor = sqlite.select(Source).project(Depth, depth=token)
    seed = anchor.cte(SeedRole, name="seed")
    step = sqlite.select(seed).project(Depth, depth=seed.column(token).add(1))

    compiled = anchor.union_all(step).compile()

    assert_eq(compiled.params, (0, 0, 1))


@test(mark="fast")
def literal_output_compares_as_a_native_integer() -> None:
    """The recursive depth predicate must bind through the literal's native policy."""
    token = sqlite.literal(0).label("depth")
    seed = sqlite.select(Source).project(Depth, depth=token).cte(SeedRole, name="seed")

    compiled = sqlite.select(seed).where(seed.column(token).lt(3)).compile()

    assert_eq(compiled.params, (0, 3))


@test(
    [
        Param(value, name=str(index))
        for index, value in enumerate(
            (None, True, False, 1.5, "0", 2**63, -(2**63) - 1)
        )
    ],
    mark="fast",
)
def invalid_native_literal_is_rejected(value: object) -> None:
    """Neither untyped NULL nor coercion can establish an integer anchor domain."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.literal(value)  # ty: ignore[invalid-argument-type]
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.literal(value)  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def literal_cannot_cross_backend_namespaces() -> None:
    """Owner freedom must not erase the constant's backend identity."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(Source).project(Depth, depth=mariadb.literal(0))  # ty: ignore[invalid-argument-type]
    with assert_raises(mariadb.QueryConstructionError):
        mariadb.select(NativeSource).project(Depth, depth=sqlite.literal(0))  # ty: ignore[invalid-argument-type]


@test(mark="fast")
def literal_does_not_supply_an_implicit_from_table() -> None:
    """Constants are projected from explicit sources, never fake tables."""
    with assert_raises(sqlite.QueryConstructionError):
        sqlite.select(sqlite.literal(0))  # ty: ignore[no-matching-overload]


@test(mark="fast")
def cte_literal_supports_numeric_aggregation() -> None:
    """A rebound integer constant has a known native aggregate input domain."""
    token = sqlite.literal(1).label("depth")
    seed = sqlite.select(Source).project(Depth, depth=token).cte(SeedRole, name="seed")

    compiled = sqlite.select(seed.column(token).sum()).compile()

    assert_eq(compiled.params, (1,))
