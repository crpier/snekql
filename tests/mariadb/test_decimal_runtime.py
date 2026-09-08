"""MariaDB native Decimal runtime behavior tests."""

from __future__ import annotations

from decimal import Decimal, Inexact, Rounded, localcontext

from snektest import assert_eq, load_fixture, test

from snekql import mariadb
from snekql.mariadb import Fetched, Pending, insert, select
from tests.helpers import initialized_database, provide_mariadb_server


class OrderedPrice[S = Pending](mariadb.Model[S, "OrderedPrice[Fetched]"]):
    """Price table with native numeric decimal storage."""

    __tablename__ = "native_decimal_order_price"

    id: OrderedPrice.Col[int] = mariadb.Integer(primary_key=True)
    amount: OrderedPrice.Col[Decimal] = mariadb.Decimal(5, 2, nullable=False)


class SummedPrice[S = Pending](mariadb.Model[S, "SummedPrice[Fetched]"]):
    """Price table for native decimal aggregation."""

    __tablename__ = "native_decimal_sum_price"

    id: SummedPrice.Col[int] = mariadb.Integer(primary_key=True)
    amount: SummedPrice.Col[Decimal] = mariadb.Decimal(5, 2, nullable=False)


@test(mark="medium")
async def mariadb_decimal_columns_order_by_numeric_value() -> None:
    """Native Decimal columns order and range-filter by numeric value."""

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(), models=[OrderedPrice])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(OrderedPrice(id=1, amount=Decimal("9.00"))))
            await tx.execute(insert(OrderedPrice(id=2, amount=Decimal("10.00"))))
            await tx.execute(insert(OrderedPrice(id=3, amount=Decimal("1.50"))))
            ordered_ids = await tx.fetch_all(
                select(OrderedPrice.id).all().order_by(OrderedPrice.amount.asc())
            )
            range_ids = await tx.fetch_all(
                select(OrderedPrice.id)
                .where(OrderedPrice.amount.gte(Decimal("9.00")))
                .order_by(OrderedPrice.id.asc())
            )
    finally:
        await database.close()

    assert_eq(ordered_ids, [3, 1, 2])
    assert_eq(range_ids, [1, 2])


@test(mark="medium")
async def mariadb_decimal_sum_returns_decimal_value() -> None:
    """Summing a native Decimal column materializes a Decimal result."""

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(server.config(), models=[SummedPrice])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(SummedPrice(id=1, amount=Decimal("1.50"))))
            await tx.execute(insert(SummedPrice(id=2, amount=Decimal("2.25"))))
            total = await tx.fetch_one(select(SummedPrice.amount.sum()).all())
    finally:
        await database.close()

    assert_eq(total, Decimal("3.75"))


@test(mark="slow")
async def mariadb_decimal_round_trip_preserves_maximum_precision() -> None:
    """Native DECIMAL(65,30) values do not depend on the application's decimal context."""

    server = await load_fixture(provide_mariadb_server())

    class PrecisePrice[S = Pending](mariadb.Model[S, "PrecisePrice[Fetched]"]):
        """A native decimal at the backend's maximum declared precision."""

        amount: PrecisePrice.Col[Decimal] = mariadb.Decimal(65, 30)

    async with await initialized_database(
        server.config(), models=[PrecisePrice]
    ) as database:
        exact = Decimal(
            "12345678901234567890123456789012345.123456789012345678901234567890"
        )
        with localcontext(prec=6, Emax=9, Emin=-9) as context:
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            async with database.transaction() as transaction:
                await transaction.execute(insert(PrecisePrice(amount=exact)))
            async with database.transaction() as transaction:
                stored = await transaction.fetch_one(select(PrecisePrice.amount).all())

    assert_eq(stored, exact)
