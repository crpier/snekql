"""Atomic numeric updates through real backend transactions."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, assert_type

from anyio import to_thread
from snektest import assert_eq, assert_raises, fixture, load_fixture, test

from snekql import mariadb, sqlite
from tests.helpers import provide_mariadb_server
from tests.query.test_arithmetic import Inventory, NumericValues


class MariaInventory[S = mariadb.Pending](mariadb.Model[S]):
    """Stock and optimistic version counters on MariaDB."""

    __row_type__: ClassVar[mariadb.ReadType[MariaInventory[mariadb.Row]]]

    id: MariaInventory.Col[int] = mariadb.Integer(primary_key=True)
    quantity: MariaInventory.Col[int] = mariadb.Integer()
    version: MariaInventory.Col[int] = mariadb.Integer()


@fixture
async def provide_sqlite_inventory() -> AsyncGenerator[sqlite.Database]:
    """Seed stock before competing transactions begin."""
    directory = await to_thread.run_sync(TemporaryDirectory[str])
    try:
        async with await sqlite.Database.initialize(
            database=Path(directory.name) / "inventory.db", pool_size=3
        ) as database:
            await database.migrate({"001_inventory": sqlite.scaffold([Inventory])})
            async with database.transaction() as transaction:
                await transaction.execute(
                    sqlite.insert(Inventory(id=1, quantity=3, version=1))
                )
            yield database
    finally:
        await to_thread.run_sync(directory.cleanup)


@fixture
async def provide_mariadb_inventory() -> AsyncGenerator[mariadb.Database]:
    """Seed stock on a real MariaDB server."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_inventory": mariadb.scaffold([MariaInventory])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert(MariaInventory(id=1, quantity=3, version=1))
            )
        yield database


@test(mark="medium")
async def integer_projection_materializes_computed_value() -> None:
    """The result is an integer expression value, not a model column decoder."""
    database = await load_fixture(provide_sqlite_inventory())

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(Inventory.quantity.sub(2).mul(3).add(1)).all()
        )

    assert_type(rows, list[int])
    assert_eq(rows, [4])


@test(mark="medium")
async def sqlite_competing_decrements_cannot_oversell() -> None:
    """The stock predicate and decrement run in one atomic statement."""
    database = await load_fixture(provide_sqlite_inventory())
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to_expr(Inventory.quantity.sub(1)),
        )
        .where(Inventory.id.eq(1) & Inventory.quantity.gte(1))
    )

    async def buy_one() -> int:
        async with database.transaction() as transaction:
            return await transaction.execute(query)

    affected = await asyncio.gather(*(buy_one() for _ in range(6)))
    async with database.transaction() as transaction:
        remaining = await transaction.fetch_one(sqlite.select(Inventory.quantity).all())

    assert_eq((sum(affected), remaining), (3, 0))


@test(mark="medium")
async def sqlite_optimistic_update_has_one_winner() -> None:
    """Only one transaction can claim the expected version."""
    database = await load_fixture(provide_sqlite_inventory())
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.quantity.to_expr(Inventory.quantity.sub(1)),
            Inventory.version.to_expr(Inventory.version.add(1)),
        )
        .where(Inventory.id.eq(1) & Inventory.version.eq(1))
    )

    async def claim_version() -> int:
        async with database.transaction() as transaction:
            return await transaction.execute(query)

    affected = await asyncio.gather(*(claim_version() for _ in range(6)))
    async with database.transaction() as transaction:
        stored = await transaction.fetch_one(
            sqlite.select(Inventory.quantity, Inventory.version).all()
        )

    assert_eq((sum(affected), stored), (1, (2, 2)))


@test(mark="slow")
async def mariadb_competing_decrements_cannot_oversell() -> None:
    """The stock predicate and decrement run in one atomic statement."""
    database = await load_fixture(provide_mariadb_inventory())
    query = (
        mariadb.update(MariaInventory)
        .set(
            MariaInventory.quantity.to_expr(MariaInventory.quantity.sub(1)),
        )
        .where(MariaInventory.id.eq(1) & MariaInventory.quantity.gte(1))
    )

    async def buy_one() -> int:
        async with database.transaction() as transaction:
            return await transaction.execute(query)

    affected = await asyncio.gather(*(buy_one() for _ in range(6)))
    async with database.transaction() as transaction:
        remaining = await transaction.fetch_one(
            mariadb.select(MariaInventory.quantity).all()
        )

    assert_eq((sum(affected), remaining), (3, 0))


@test(mark="slow")
async def mariadb_optimistic_update_has_one_winner() -> None:
    """Only one transaction can claim the expected version."""
    database = await load_fixture(provide_mariadb_inventory())
    query = (
        mariadb.update(MariaInventory)
        .set(
            MariaInventory.quantity.to_expr(MariaInventory.quantity.sub(1)),
            MariaInventory.version.to_expr(MariaInventory.version.add(1)),
        )
        .where(MariaInventory.id.eq(1) & MariaInventory.version.eq(1))
    )

    async def claim_version() -> int:
        async with database.transaction() as transaction:
            return await transaction.execute(query)

    affected = await asyncio.gather(*(claim_version() for _ in range(6)))
    async with database.transaction() as transaction:
        stored = await transaction.fetch_one(
            mariadb.select(MariaInventory.quantity, MariaInventory.version).all()
        )

    assert_eq((sum(affected), stored), (1, (2, 2)))


@test(mark="medium")
async def sqlite_integer_overflow_is_not_decoded_as_integer() -> None:
    """SQLite promotes overflowing integer arithmetic to REAL; do not truncate it."""
    database = await load_fixture(provide_sqlite_inventory())

    async with database.transaction() as transaction:
        with assert_raises(sqlite.ModelValidationError):
            await transaction.fetch_all(
                sqlite.select(Inventory.quantity.add(2**63 - 1)).all()
            )


@test(mark="slow")
async def mariadb_integer_overflow_remains_an_execution_error() -> None:
    """MariaDB's numeric range failure is preserved, not turned into a value."""
    database = await load_fixture(provide_mariadb_inventory())

    async with database.transaction() as transaction:
        with assert_raises(mariadb.ExecutionError):
            await transaction.fetch_all(
                mariadb.select(MariaInventory.quantity.add(2**63 - 1)).all()
            )


class MariaNumericValues[S = mariadb.Pending](mariadb.Model[S]):
    """Native numeric domains with independently nullable columns."""

    __row_type__: ClassVar[mariadb.ReadType[MariaNumericValues[mariadb.Row]]]

    id: MariaNumericValues.Col[int] = mariadb.Integer(primary_key=True)
    integer: MariaNumericValues.Col[int] = mariadb.Integer()
    optional_integer: MariaNumericValues.Col[int | None] = mariadb.Integer(
        nullable=True
    )
    real: MariaNumericValues.Col[float] = mariadb.Real()
    optional_real: MariaNumericValues.Col[float | None] = mariadb.Real(nullable=True)


@fixture
async def provide_sqlite_numeric_values() -> AsyncGenerator[sqlite.Database]:
    """Seed both missing and present numeric operands."""
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate({"001_numeric": sqlite.scaffold([NumericValues])})
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.insert_many(
                    NumericValues,
                    [
                        NumericValues(
                            id=1,
                            integer=4,
                            optional_integer=None,
                            real=2.5,
                            optional_real=None,
                        ),
                        NumericValues(
                            id=2,
                            integer=4,
                            optional_integer=3,
                            real=2.5,
                            optional_real=1.5,
                        ),
                    ],
                )
            )
        yield database


@test(mark="medium")
async def sqlite_arithmetic_propagates_null_from_either_operand() -> None:
    """A nullable operand changes the result contract on either side of arithmetic."""
    database = await load_fixture(provide_sqlite_numeric_values())
    query = (
        sqlite.select(
            NumericValues.integer.add(NumericValues.optional_integer),
            NumericValues.optional_integer.sub(NumericValues.integer),
            NumericValues.real.mul(2.0).add(NumericValues.optional_real),
        )
        .all()
        .order_by(NumericValues.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int | None, int | None, float | None]])
    assert_eq(rows, [(None, None, None), (7, -1, 6.5)])


@test(mark="medium")
async def sqlite_nullable_assignment_accepts_non_null_expression() -> None:
    """A computed non-null value can fill optional storage without a cast."""
    database = await load_fixture(provide_sqlite_numeric_values())

    async with database.transaction() as transaction:
        await transaction.execute(
            sqlite.update(NumericValues)
            .set(
                NumericValues.optional_real.to_expr(NumericValues.real.mul(2.0)),
            )
            .all()
        )
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(NumericValues.optional_real).all()
        )

    assert_type(rows, list[float | None])
    assert_eq(rows, [5.0, 5.0])


@test(mark="medium")
async def sqlite_nullable_assignment_preserves_sql_null() -> None:
    """Updating a missing numeric value with arithmetic leaves it missing."""
    database = await load_fixture(provide_sqlite_numeric_values())

    async with database.transaction() as transaction:
        await transaction.execute(
            sqlite.update(NumericValues)
            .set(
                NumericValues.optional_real.to_expr(
                    NumericValues.optional_real.mul(2.0)
                ),
            )
            .all()
        )
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            sqlite.select(NumericValues.optional_real)
            .all()
            .order_by(NumericValues.id.asc())
        )

    assert_eq(rows, [None, 3.0])


@fixture
async def provide_mariadb_numeric_values() -> AsyncGenerator[mariadb.Database]:
    """Seed both missing and present numeric operands."""
    server = await load_fixture(provide_mariadb_server())
    async with await mariadb.Database.initialize(server.config()) as database:
        await database.migrate({"001_numeric": mariadb.scaffold([MariaNumericValues])})
        async with database.transaction() as transaction:
            await transaction.execute(
                mariadb.insert_many(
                    MariaNumericValues,
                    [
                        MariaNumericValues(
                            id=1,
                            integer=4,
                            optional_integer=None,
                            real=2.5,
                            optional_real=None,
                        ),
                        MariaNumericValues(
                            id=2,
                            integer=4,
                            optional_integer=3,
                            real=2.5,
                            optional_real=1.5,
                        ),
                    ],
                )
            )
        yield database


@test(mark="slow")
async def mariadb_arithmetic_propagates_null_from_either_operand() -> None:
    """A nullable operand changes the result contract on either side of arithmetic."""
    database = await load_fixture(provide_mariadb_numeric_values())
    query = (
        mariadb.select(
            MariaNumericValues.integer.add(MariaNumericValues.optional_integer),
            MariaNumericValues.optional_integer.sub(MariaNumericValues.integer),
            MariaNumericValues.real.mul(2.0).add(MariaNumericValues.optional_real),
        )
        .all()
        .order_by(MariaNumericValues.id.asc())
    )

    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(query)

    assert_type(rows, list[tuple[int | None, int | None, float | None]])
    assert_eq(rows, [(None, None, None), (7, -1, 6.5)])


@test(mark="slow")
async def mariadb_nullable_assignment_accepts_non_null_expression() -> None:
    """A computed non-null value can fill optional storage without a cast."""
    database = await load_fixture(provide_mariadb_numeric_values())

    async with database.transaction() as transaction:
        await transaction.execute(
            mariadb.update(MariaNumericValues)
            .set(
                MariaNumericValues.optional_real.to_expr(
                    MariaNumericValues.real.mul(2.0)
                ),
            )
            .all()
        )
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(MariaNumericValues.optional_real).all()
        )

    assert_type(rows, list[float | None])
    assert_eq(rows, [5.0, 5.0])


@test(mark="slow")
async def mariadb_nullable_assignment_preserves_sql_null() -> None:
    """Updating a missing numeric value with arithmetic leaves it missing."""
    database = await load_fixture(provide_mariadb_numeric_values())

    async with database.transaction() as transaction:
        await transaction.execute(
            mariadb.update(MariaNumericValues)
            .set(
                MariaNumericValues.optional_real.to_expr(
                    MariaNumericValues.optional_real.mul(2.0)
                ),
            )
            .all()
        )
    async with database.transaction() as transaction:
        rows = await transaction.fetch_all(
            mariadb.select(MariaNumericValues.optional_real)
            .all()
            .order_by(MariaNumericValues.id.asc())
        )

    assert_eq(rows, [None, 3.0])


@test(mark="medium")
async def sqlite_concurrent_increments_do_not_lose_updates() -> None:
    """Every committed statement increments the current counter value once."""
    database = await load_fixture(provide_sqlite_inventory())
    query = (
        sqlite.update(Inventory)
        .set(
            Inventory.version.to_expr(Inventory.version.add(1)),
        )
        .where(Inventory.id.eq(1))
    )

    async def increment() -> None:
        async with database.transaction() as transaction:
            await transaction.execute(query)

    await asyncio.gather(*(increment() for _ in range(6)))
    async with database.transaction() as transaction:
        version = await transaction.fetch_one(sqlite.select(Inventory.version).all())

    assert_eq(version, 7)


@test(mark="slow")
async def mariadb_concurrent_increments_do_not_lose_updates() -> None:
    """Every committed statement increments the current counter value once."""
    database = await load_fixture(provide_mariadb_inventory())
    query = (
        mariadb.update(MariaInventory)
        .set(
            MariaInventory.version.to_expr(MariaInventory.version.add(1)),
        )
        .where(MariaInventory.id.eq(1))
    )

    async def increment() -> None:
        async with database.transaction() as transaction:
            await transaction.execute(query)

    await asyncio.gather(*(increment() for _ in range(6)))
    async with database.transaction() as transaction:
        version = await transaction.fetch_one(
            mariadb.select(MariaInventory.version).all()
        )

    assert_eq(version, 7)
