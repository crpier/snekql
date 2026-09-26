"""Column comparisons retain nullable and scalar behavior on native backends."""

from typing import ClassVar, assert_type

from snektest import Param, assert_eq, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import initialized_database, provide_mariadb_server


@test(
    [
        Param((operator, expected), name=operator)
        for operator, expected in (
            ("eq", [2]),
            ("ne", [1, 3]),
            ("gt", [3]),
            ("gte", [2, 3]),
            ("lt", [1]),
            ("lte", [1, 2]),
        )
    ],
    mark="medium",
)
async def sqlite_column_comparisons_preserve_values(
    case: tuple[str, list[int]],
) -> None:
    """SQL NULL does not match; a scalar's inner table needs no outer join."""

    operator, expected = case

    class Reading[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Reading[sqlite.Row]]]
        amount: sqlite.Col[int] = sqlite.Integer()

    class Threshold[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Threshold[sqlite.Row]]]
        amount: sqlite.Col[int | None] = sqlite.Integer(default=None)

    async with await initialized_database(
        database=":memory:", models=[Reading, Threshold]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.insert_many(
                    Reading, [Reading(amount=1), Reading(amount=2), Reading(amount=3)]
                )
            )
            await setup.execute(
                sqlite.insert_many(
                    Threshold, [Threshold(amount=2), Threshold(amount=None)]
                )
            )

        operand = Threshold.amount
        predicates = {
            "eq": Reading.amount.eq_col(operand),
            "ne": Reading.amount.ne_col(operand),
            "gt": Reading.amount.gt_col(operand),
            "gte": Reading.amount.gte_col(operand),
            "lt": Reading.amount.lt_col(operand),
            "lte": Reading.amount.lte_col(operand),
        }
        query = sqlite.select(Reading.amount).join(Threshold, on=predicates[operator])
        async with database.transaction() as transaction:
            amounts = await transaction.fetch_all(query.order_by(Reading.amount.asc()))

    assert_type(amounts, list[int])
    assert_eq(amounts, expected)


@test(
    [
        Param((operator, expected), name=operator)
        for operator, expected in (
            ("eq", [2]),
            ("ne", [1, 3]),
            ("gt", [3]),
            ("gte", [2, 3]),
            ("lt", [1]),
            ("lte", [1, 2]),
        )
    ],
    mark="medium",
)
async def sqlite_scalar_comparisons_preserve_values(
    case: tuple[str, list[int]],
) -> None:
    """SQL NULL does not match; a scalar's inner table needs no outer join."""

    operator, expected = case

    class Reading[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Reading[sqlite.Row]]]
        amount: sqlite.Col[int] = sqlite.Integer()

    class Threshold[State = sqlite.Pending](sqlite.Model[State]):
        __row_type__: ClassVar[sqlite.ReadType[Threshold[sqlite.Row]]]
        amount: sqlite.Col[int | None] = sqlite.Integer(default=None)

    async with await initialized_database(
        database=":memory:", models=[Reading, Threshold]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                sqlite.insert_many(
                    Reading, [Reading(amount=1), Reading(amount=2), Reading(amount=3)]
                )
            )
            await setup.execute(
                sqlite.insert_many(
                    Threshold, [Threshold(amount=2), Threshold(amount=None)]
                )
            )

        operand = sqlite.scalar(
            sqlite.select(Threshold.amount)
            .where(Threshold.amount.is_not_null())
            .limit(1)
        )
        predicates = {
            "eq": Reading.amount.eq_col(operand),
            "ne": Reading.amount.ne_col(operand),
            "gt": Reading.amount.gt_col(operand),
            "gte": Reading.amount.gte_col(operand),
            "lt": Reading.amount.lt_col(operand),
            "lte": Reading.amount.lte_col(operand),
        }
        query = sqlite.select(Reading.amount).where(predicates[operator])
        async with database.transaction() as transaction:
            amounts = await transaction.fetch_all(query.order_by(Reading.amount.asc()))

    assert_type(amounts, list[int])
    assert_eq(amounts, expected)


@test(
    [
        Param((operator, expected), name=operator)
        for operator, expected in (
            ("eq", [2]),
            ("ne", [1, 3]),
            ("gt", [3]),
            ("gte", [2, 3]),
            ("lt", [1]),
            ("lte", [1, 2]),
        )
    ],
    mark="slow",
)
async def mariadb_column_comparisons_preserve_values(
    case: tuple[str, list[int]],
) -> None:
    """SQL NULL does not match; a scalar's inner table needs no outer join."""

    server = await load_fixture(provide_mariadb_server())
    operator, expected = case

    class Reading[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Reading[mariadb.Row]]]
        amount: mariadb.Col[int] = mariadb.Integer()

    class Threshold[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Threshold[mariadb.Row]]]
        amount: mariadb.Col[int | None] = mariadb.Integer(default=None)

    async with await initialized_database(
        server.config(), models=[Reading, Threshold]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert_many(
                    Reading, [Reading(amount=1), Reading(amount=2), Reading(amount=3)]
                )
            )
            await setup.execute(
                mariadb.insert_many(
                    Threshold, [Threshold(amount=2), Threshold(amount=None)]
                )
            )

        operand = Threshold.amount
        predicates = {
            "eq": Reading.amount.eq_col(operand),
            "ne": Reading.amount.ne_col(operand),
            "gt": Reading.amount.gt_col(operand),
            "gte": Reading.amount.gte_col(operand),
            "lt": Reading.amount.lt_col(operand),
            "lte": Reading.amount.lte_col(operand),
        }
        query = mariadb.select(Reading.amount).join(Threshold, on=predicates[operator])
        async with database.transaction() as transaction:
            amounts = await transaction.fetch_all(query.order_by(Reading.amount.asc()))

    assert_type(amounts, list[int])
    assert_eq(amounts, expected)


@test(
    [
        Param((operator, expected), name=operator)
        for operator, expected in (
            ("eq", [2]),
            ("ne", [1, 3]),
            ("gt", [3]),
            ("gte", [2, 3]),
            ("lt", [1]),
            ("lte", [1, 2]),
        )
    ],
    mark="slow",
)
async def mariadb_scalar_comparisons_preserve_values(
    case: tuple[str, list[int]],
) -> None:
    """SQL NULL does not match; a scalar's inner table needs no outer join."""

    server = await load_fixture(provide_mariadb_server())
    operator, expected = case

    class Reading[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Reading[mariadb.Row]]]
        amount: mariadb.Col[int] = mariadb.Integer()

    class Threshold[State = mariadb.Pending](mariadb.Model[State]):
        __row_type__: ClassVar[mariadb.ReadType[Threshold[mariadb.Row]]]
        amount: mariadb.Col[int | None] = mariadb.Integer(default=None)

    async with await initialized_database(
        server.config(), models=[Reading, Threshold]
    ) as database:
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.insert_many(
                    Reading, [Reading(amount=1), Reading(amount=2), Reading(amount=3)]
                )
            )
            await setup.execute(
                mariadb.insert_many(
                    Threshold, [Threshold(amount=2), Threshold(amount=None)]
                )
            )

        operand = mariadb.scalar(
            mariadb.select(Threshold.amount)
            .where(Threshold.amount.is_not_null())
            .limit(1)
        )
        predicates = {
            "eq": Reading.amount.eq_col(operand),
            "ne": Reading.amount.ne_col(operand),
            "gt": Reading.amount.gt_col(operand),
            "gte": Reading.amount.gte_col(operand),
            "lt": Reading.amount.lt_col(operand),
            "lte": Reading.amount.lte_col(operand),
        }
        query = mariadb.select(Reading.amount).where(predicates[operator])
        async with database.transaction() as transaction:
            amounts = await transaction.fetch_all(query.order_by(Reading.amount.asc()))

    assert_type(amounts, list[int])
    assert_eq(amounts, expected)
