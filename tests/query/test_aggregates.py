"""Ungrouped scalar aggregate construction, compilation, and decode tests.

Aggregates are a selectable expression produced by column methods
(``Order.amount.sum()``) and a model classmethod for ``COUNT(*)``
(``User.count_all()``). A lone aggregate select yields one scalar per query and is
identical SQL in SQLite and MariaDB. ``GROUP BY``/``HAVING`` are separate slices
(#112, #113); this module covers ungrouped scalar aggregation only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from snektest import assert_eq, assert_raises, test

from snekql import sqlite
from snekql.mariadb.query import compile_mariadb_select_sql
from snekql.sqlite import (
    PENDING_GENERATION,
    Fetched,
    Integer,
    Model,
    Pending,
    QueryConstructionError,
    Real,
    Text,
    UtcDatetime,
    insert,
    select,
)
from snekql.sqlite.query import compile_sqlite_select_sql
from tests.helpers import initialized_database


class User[S = Pending](sqlite.Model[S, "User[Fetched]"]):
    """Base table for aggregate compilation tests."""

    id: User.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: User.Col[str] = sqlite.Text(nullable=False)


class Order[S = Pending](sqlite.Model[S, "Order[Fetched]"]):
    """Table with numeric columns to aggregate over."""

    id: Order.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    user_id: Order.FKCol[User, int] = sqlite.ForeignKey(User.id)
    amount: Order.Col[int] = sqlite.Integer(nullable=False)


@test(mark="fast")
def count_star_compiles_to_count_all() -> None:
    """A model ``_count()`` renders ``COUNT(*)``."""

    sql, params = compile_sqlite_select_sql(select(User.count_all()).all())

    assert_eq(sql, 'SELECT COUNT(*) FROM "user"')
    assert_eq(params, ())


@test(mark="fast")
def count_column_compiles_to_count_of_column() -> None:
    """A column ``.count()`` renders ``COUNT(col)``."""

    sql, params = compile_sqlite_select_sql(select(User.id.count()).all())

    assert_eq(sql, 'SELECT COUNT("id") FROM "user"')
    assert_eq(params, ())


@test(mark="fast")
def sum_avg_min_max_compile_to_their_functions() -> None:
    """Each column aggregate renders its SQL function over the column."""

    assert_eq(
        compile_sqlite_select_sql(select(Order.amount.sum()).all())[0],
        'SELECT SUM("amount") FROM "order"',
    )
    assert_eq(
        compile_sqlite_select_sql(select(Order.amount.avg()).all())[0],
        'SELECT AVG("amount") FROM "order"',
    )
    assert_eq(
        compile_sqlite_select_sql(select(Order.amount.min()).all())[0],
        'SELECT MIN("amount") FROM "order"',
    )
    assert_eq(
        compile_sqlite_select_sql(select(Order.amount.max()).all())[0],
        'SELECT MAX("amount") FROM "order"',
    )


@test(mark="fast")
def aggregate_compiles_with_where() -> None:
    """An aggregate composes with a WHERE filter over the same table."""

    sql, params = compile_sqlite_select_sql(
        select(Order.amount.sum()).where(Order.amount.gt(10)),
    )

    assert_eq(sql, 'SELECT SUM("amount") FROM "order" WHERE ("amount" > ?)')
    assert_eq(params, (10,))


@test(mark="fast")
def count_star_is_backend_portable() -> None:
    """COUNT(*) is identical SQL in MariaDB save for identifier quoting."""

    assert_eq(
        compile_mariadb_select_sql(select(User.count_all()).all())[0],
        "SELECT COUNT(*) FROM `user`",
    )


@test(mark="medium")
async def count_returns_row_count_at_runtime() -> None:
    """An ungrouped COUNT(*) fetches as a plain int scalar."""

    database = await initialized_database(database=":memory:", models=[User])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="a@example.com")))
            await tx.execute(insert(User(email="b@example.com")))
            total = await tx.fetch_one(select(User.count_all()).all())
    finally:
        await database.close()

    assert_eq(total, 2)


@test(mark="medium")
async def sum_normalizes_to_int_for_integer_column() -> None:
    """SUM over an Integer column decodes to int; over no rows decodes to None."""

    class Sale[S = Pending](Model[S, "Sale[Fetched]"]):
        """Integer-amount table for sum normalization."""

        id: Sale.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        amount: Sale.Col[int] = Integer(nullable=False)

    database = await initialized_database(database=":memory:", models=[Sale])
    try:
        async with database.transaction() as tx:
            empty = await tx.fetch_one(select(Sale.amount.sum()).all())
            await tx.execute(insert(Sale(amount=3)))
            await tx.execute(insert(Sale(amount=4)))
            total = await tx.fetch_one(select(Sale.amount.sum()).all())
    finally:
        await database.close()

    assert_eq(empty, None)
    assert_eq(total, 7)
    assert isinstance(total, int)


@test(mark="fast")
def sum_and_avg_reject_non_numeric_columns() -> None:
    """SUM/AVG over a non-numeric column coerce to a float in SQLite, so the
    column's logical read type would not describe the result; reject them.
    """

    with assert_raises(QueryConstructionError):
        _ = User.email.sum()
    with assert_raises(QueryConstructionError):
        _ = User.email.avg()


@test(mark="fast")
def sum_and_avg_allow_numeric_columns() -> None:
    """SUM/AVG over numeric columns build without objection."""

    _ = Order.amount.sum()
    _ = Order.amount.avg()


@test(mark="medium")
async def min_and_max_decode_datetime_to_logical_type() -> None:
    """MIN/MAX over a TEXT-stored datetime decode to ``datetime``, not raw text.

    The wire->logical coercion that a normal column select performs must also run
    for MIN/MAX, otherwise the static ``datetime | None`` type is unsound.
    """

    class Event[S = Pending](Model[S, "Event[Fetched]"]):
        """Datetime table stored as TEXT on SQLite."""

        id: Event.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        when: Event.Col[UtcDatetime] = Text(nullable=False)

    earlier = datetime(2020, 1, 1, tzinfo=UTC)
    later = datetime(2021, 6, 15, tzinfo=UTC)
    database = await initialized_database(database=":memory:", models=[Event])
    try:
        async with database.transaction() as tx:
            await tx.execute(insert(Event(when=earlier)))
            await tx.execute(insert(Event(when=later)))
            lowest = await tx.fetch_one(select(Event.when.min()).all())
            highest = await tx.fetch_one(select(Event.when.max()).all())
    finally:
        await database.close()

    assert isinstance(lowest, datetime)
    assert isinstance(highest, datetime)
    assert_eq(lowest, earlier)
    assert_eq(highest, later)


@test(mark="fast")
def aggregate_over_unjoined_table_is_a_construction_error() -> None:
    """Filtering an aggregate by an un-joined table's column is rejected."""

    with assert_raises(QueryConstructionError):
        _ = select(Order.amount.sum()).where(User.email.eq("a@example.com"))


@test(mark="medium")
async def min_and_max_decode_to_column_type_and_none_over_empty() -> None:
    """MIN/MAX reuse the column's decode; an empty set decodes to None."""

    class Label[S = Pending](Model[S, "Label[Fetched]"]):
        """Text table for min/max decoding."""

        id: Label.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        name: Label.Col[str] = Text(nullable=False)

    database = await initialized_database(database=":memory:", models=[Label])
    try:
        async with database.transaction() as tx:
            empty = await tx.fetch_one(select(Label.name.min()).all())
            await tx.execute(insert(Label(name="beta")))
            await tx.execute(insert(Label(name="alpha")))
            await tx.execute(insert(Label(name="gamma")))
            lowest = await tx.fetch_one(select(Label.name.min()).all())
            highest = await tx.fetch_one(select(Label.name.max()).all())
    finally:
        await database.close()

    assert_eq(empty, None)
    assert_eq(lowest, "alpha")
    assert_eq(highest, "gamma")


@test(mark="medium")
async def avg_decodes_to_float_and_none_over_empty() -> None:
    """AVG decodes to float, and to None over an empty set."""

    class Reading[S = Pending](Model[S, "Reading[Fetched]"]):
        """Real-valued table for avg decoding."""

        id: Reading.GenCol[int] = Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        value: Reading.Col[float] = Real(nullable=False)

    database = await initialized_database(database=":memory:", models=[Reading])
    try:
        async with database.transaction() as tx:
            empty = await tx.fetch_one(select(Reading.value.avg()).all())
            await tx.execute(insert(Reading(value=2.0)))
            await tx.execute(insert(Reading(value=3.0)))
            mean = await tx.fetch_one(select(Reading.value.avg()).all())
    finally:
        await database.close()

    assert_eq(empty, None)
    assert_eq(mean, 2.5)
    assert isinstance(mean, float)
