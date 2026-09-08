"""Integer totals use MariaDB's widened aggregate domain."""

from __future__ import annotations

from typing import Annotated

from pydantic import PlainSerializer
from snektest import Param, assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import mariadb, sqlite
from snekql.errors import ModelValidationError
from tests.helpers import initialized_database, provide_mariadb_server


@test(
    [Param(value=1, name="positive"), Param(value=-1, name="negative")],
    [Param(value=kind, name=kind) for kind in ("eq", "between", "in")],
    mark="slow",
)
async def sum_bound_exceeds_bigint(sign: int, kind: str) -> None:
    """Two valid inputs can be compared to their exact widened total."""
    server = await load_fixture(provide_mariadb_server())

    class Quantity[S = mariadb.Pending](mariadb.Model[S, "Quantity[mariadb.Fetched]"]):
        amount: Quantity.Col[int] = mariadb.Integer(nullable=False)

    async with await initialized_database(
        server.config(), models=[Quantity]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Quantity(amount=sign * (2**62 + 1))))
            await setup.execute(mariadb.insert(Quantity(amount=sign * (2**62 + 1))))
        total = Quantity.amount.sum()
        bound = sign * 9223372036854775810
        predicate = {
            "eq": total.eq(bound),
            "between": total.between(bound - 1, bound + 1),
            "in": total.in_(0, bound),
        }[kind]
        query = mariadb.select(total).all().having(predicate)
        assert_in(str(bound if kind != "between" else bound - 1), repr(query))
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)
    assert_eq(rows, [bound])


def _double(value: int) -> int:
    """Make logical serialization observable in query parameters."""
    return value * 2


@test(mark="slow")
async def sum_bound_retains_integer_serializer() -> None:
    """Serialization still applies when its exact result exceeds BIGINT."""
    server = await load_fixture(provide_mariadb_server())

    class Quantity[S = mariadb.Pending](mariadb.Model[S, "Quantity[mariadb.Fetched]"]):
        amount: Quantity.Col[Annotated[int, PlainSerializer(_double)]] = (
            mariadb.Integer(nullable=False)
        )

    async with await initialized_database(
        server.config(), models=[Quantity]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(mariadb.insert(Quantity(amount=2**61 + 1)))
            await setup.execute(mariadb.insert(Quantity(amount=2**61 + 1)))
        query = (
            mariadb.select(Quantity.amount.sum())
            .all()
            .having(Quantity.amount.sum().eq(2**62 + 2))
        )
        assert_in("params=(9223372036854775812,)", repr(query))
        async with database.transaction() as tx:
            rows = await tx.fetch_all(query)
    assert_eq(rows, [9223372036854775812])


@test(
    [Param(value=sign, name=str(sign)) for sign in (1, -1)],
    [Param(value=kind, name=kind) for kind in ("insert", "update")],
    mark="slow",
)
async def oversized_bigint_write_rejected(sign: int, kind: str) -> None:
    """Widened HAVING encoding does not weaken the individual row limit."""
    server = await load_fixture(provide_mariadb_server())

    class Quantity[S = mariadb.Pending](mariadb.Model[S, "Quantity[mariadb.Fetched]"]):
        amount: Quantity.Col[int] = mariadb.Integer(nullable=False)

    async with (
        await initialized_database(server.config(), models=[Quantity]) as database,
        database.transaction() as tx,
    ):
        with assert_raises(ModelValidationError):
            if kind == "insert":
                await tx.execute(mariadb.insert(Quantity(amount=sign * 2**64)))
            else:
                await tx.execute(
                    mariadb.update(Quantity).set(Quantity.amount.to(sign * 2**64)).all()
                )


@test(mark="fast")
def sqlite_sum_bound_keeps_driver_limit() -> None:
    """SQLite does not gain arbitrary precision integer SUM parameters."""

    class Quantity[S = sqlite.Pending](sqlite.Model[S, "Quantity[sqlite.Fetched]"]):
        amount: Quantity.Col[int] = sqlite.Integer(nullable=False)

    query = (
        sqlite.select(Quantity.amount.sum())
        .all()
        .having(Quantity.amount.sum().eq(2**63))
    )
    with assert_raises(ModelValidationError):
        repr(query)


@test(mark="fast")
def ordinary_integer_comparisons_keep_bigint_limit() -> None:
    """Scalar and extrema comparisons keep the input column codec."""

    class Quantity[S = mariadb.Pending](mariadb.Model[S, "Quantity[mariadb.Fetched]"]):
        amount: Quantity.Col[int] = mariadb.Integer(nullable=False)

    with assert_raises(ModelValidationError):
        repr(mariadb.select(Quantity.amount).where(Quantity.amount.eq(2**63)))
    for operand in (Quantity.amount.min(), Quantity.amount.max()):
        with assert_raises(ModelValidationError):
            repr(mariadb.select(operand).all().having(operand.eq(2**63)))
