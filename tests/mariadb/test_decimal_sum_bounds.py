"""Native Decimal SUM comparisons use the result domain, not one row's shape."""

from __future__ import annotations

from decimal import Decimal, Inexact, Rounded, localcontext

from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server


class Price[S = mariadb.Pending](mariadb.Model[S, "Price[mariadb.Fetched]"]):
    """A narrow input column whose total can exceed its precision."""

    amount: Price.Col[Decimal] = mariadb.Decimal(5, 2, nullable=False)


@test(mark="medium")
async def sum_bound_can_exceed_input_precision() -> None:
    """Two legal 600 inputs can be compared against an aggregate bound of 1000."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Price]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Price(amount=Decimal(600))))
            await setup.execute(mariadb.insert(Price(amount=Decimal(600))))
        async with database.transaction() as tx:
            rows = await tx.fetch_all(
                mariadb.select(Price.amount.sum())
                .all()
                .having(Price.amount.sum().gt(Decimal(1000)))
            )

    assert_eq(rows, [Decimal(1200)])


@test(mark="medium")
async def negative_totals_support_comparisons_ranges_and_membership() -> None:
    """Negative SUM bounds support scalar, range and membership predicates."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Price]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Price(amount=Decimal(-600))))
            await setup.execute(mariadb.insert(Price(amount=Decimal(-600))))
        total = Price.amount.sum()
        for predicate in (
            total.lt(Decimal(-1000)),
            total.between(Decimal(-1300), Decimal(-1100)),
            total.in_(Decimal(2000), Decimal(-1200)),
        ):
            async with database.transaction() as tx:
                rows = await tx.fetch_all(mariadb.select(total).all().having(predicate))
            assert_eq(rows, [Decimal(-1200)])


@test(mark="medium")
async def sum_bounds_preserve_exact_digits_under_small_decimal_context() -> None:
    """A sub-cent bound must not round to the total or inherit the input scale."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Price]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Price(amount=Decimal(600))))
            await setup.execute(mariadb.insert(Price(amount=Decimal(600))))
        bound = Decimal("1200.0000000000000000000000000001")
        query = (
            mariadb.select(Price.amount.sum())
            .all()
            .having(Price.amount.sum().lt(bound))
        )
        with localcontext() as context:
            context.prec = 6
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            assert_in(f"params=({bound!r},)", repr(query))
            async with database.transaction() as tx:
                rows = await tx.fetch_all(query)

    assert_eq(rows, [Decimal(1200)])


@test(
    [
        Param(value=value, name=value)
        for value in ("NaN", "sNaN", "Infinity", "-Infinity")
    ],
    mark="fast",
)
def sum_bounds_reject_nonfinite_decimals(value: str) -> None:
    """Widening the result domain does not admit non-finite driver parameters."""

    query = (
        mariadb.select(Price.amount.sum())
        .all()
        .having(Price.amount.sum().eq(Decimal(value)))
    )
    with assert_raises(ModelValidationError):
        repr(query)


@test(
    [Param(value="insert", name="insert"), Param(value="update", name="update")],
    mark="medium",
)
async def oversized_individual_writes_still_fail(
    write_kind: str,
) -> None:
    """The SUM encoder does not replace the storage codec on writes."""

    server = await load_fixture(provide_mariadb_server())
    async with await initialized_database(server.config(), models=[Price]) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Price(amount=Decimal(600))))

        async with database.transaction() as tx:
            with assert_raises(ModelValidationError):
                if write_kind == "update":
                    await tx.execute(
                        mariadb.update(Price).set(Price.amount.to(Decimal(-1000))).all()
                    )
                else:
                    await tx.execute(mariadb.insert(Price(amount=Decimal(1000))))

        async with database.transaction() as tx:
            rows = await tx.fetch_all(mariadb.select(Price.amount).all())

    assert_eq(rows, [Decimal(600)])


@test(mark="fast")
def scalar_minimum_and_maximum_keep_the_column_codec() -> None:
    """Only SUM is widened; ordinary operands and extrema retain their codec."""

    with assert_raises(ModelValidationError):
        repr(mariadb.select(Price.amount).where(Price.amount.gt(Decimal(1000))))
    for operand in (Price.amount.min(), Price.amount.max()):
        query = mariadb.select(operand).all().having(operand.gt(Decimal(1000)))
        with assert_raises(ModelValidationError):
            repr(query)
