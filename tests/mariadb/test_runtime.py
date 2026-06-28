"""MariaDB runtime tracer-bullet integration tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from snektest import (
    AsyncFixture,
    assert_eq,
    assert_raises,
    load_fixture,
    test,
)

from snekql import mariadb
from snekql.mariadb import (
    PENDING_GENERATION,
    Database,
    DatabaseClosedError,
    ExecutionError,
    Fetched,
    Pending,
    PoolTimeoutError,
    delete,
    exists,
    insert,
    scalar,
    select,
    update,
)
from snekql.model import Table
from tests.helpers import initialized_database, provide_mariadb_server


class _RollbackSentinelError(Exception):
    """Test-only exception used to force a transaction rollback."""


class _UpdateUser[S = Pending](mariadb.Model[S, "_UpdateUser[Fetched]"]):
    """Table model for MariaDB update coverage."""

    __tablename__ = "issue38_user_update"

    id: _UpdateUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=PENDING_GENERATION,
    )
    email: _UpdateUser.Col[str] = mariadb.Text(nullable=False)
    status: _UpdateUser.Col[str] = mariadb.Text(nullable=False)


async def database_session(
    models: Sequence[type[Table[Any]]] = (),
    *,
    pool_size: int = 1,
) -> AsyncFixture[Database]:
    """Provide an initialized MariaDB Database and close it after the test."""

    server = await load_fixture(provide_mariadb_server())
    database = await initialized_database(
        server.config(pool_size=pool_size), models=models
    )
    try:
        yield database
    finally:
        await database.close()


async def database_with_update_users() -> AsyncFixture[Database]:
    """Provide a MariaDB Database seeded with update target rows."""

    database = await load_fixture(database_session([_UpdateUser]))
    async with database.transaction() as tx:
        await tx.execute(
            insert(_UpdateUser(email="alice@example.com", status="active"))
        )
        await tx.execute(insert(_UpdateUser(email="bob@example.com", status="active")))
    yield database


@test(mark="medium")
async def mariadb_runtime_creates_schema_and_round_trips_model_rows() -> None:
    """A MariaDB Database can insert, select, and close."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for the MariaDB runtime."""

        __tablename__ = "issue37_user_round_trip"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com")))

    async with database.transaction() as tx:
        fetched_user = await tx.fetch_one(
            select(User).where(User.email.eq("alice@example.com")),
        )

    assert_eq(fetched_user.email, "alice@example.com")
    assert isinstance(fetched_user.id, int)


@test(mark="medium")
async def mariadb_runtime_rolls_back_failed_transactions() -> None:
    """MariaDB Transactions roll back when the body raises."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        __tablename__ = "issue37_user_lifecycle"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    try:
        async with database.transaction() as tx:
            await tx.execute(insert(User(email="rolled-back@example.com")))
            raise _RollbackSentinelError  # noqa: TRY301
    except _RollbackSentinelError:
        pass

    async with database.transaction() as tx:
        rolled_back_user = await tx.fetch_one_or_none(
            select(User).where(User.email.eq("rolled-back@example.com")),
        )

    assert_eq(rolled_back_user, None)


@test(mark="medium")
async def mariadb_runtime_reports_pool_timeout() -> None:
    """MariaDB Database reports pool exhaustion as a timeout."""

    database = await load_fixture(database_session(pool_size=1))

    async with database.transaction():
        with assert_raises(PoolTimeoutError):
            async with database.transaction(timeout=0.01):
                pass


@test(mark="medium")
async def mariadb_runtime_rejects_transactions_after_close() -> None:
    """MariaDB Database rejects new Transactions after close."""

    database = await load_fixture(database_session())
    await database.close()

    with assert_raises(DatabaseClosedError):
        _ = database.transaction()


@test(mark="medium")
async def mariadb_runtime_fetches_scalar_rows() -> None:
    """MariaDB fetch_all returns scalar rows for single-column selects."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB scalar result coverage."""

        __tablename__ = "issue38_user_scalar_result"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com")))
        scalar_rows = await tx.fetch_all(select(User.email).all())

    assert_eq(scalar_rows, ["alice@example.com"])


@test(mark="medium")
async def mariadb_runtime_fetches_tuple_rows() -> None:
    """MariaDB fetch_all returns tuples for multi-column selects."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB tuple result coverage."""

        __tablename__ = "issue38_user_tuple_result"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com", status="active")))
        tuple_rows = await tx.fetch_all(select(User.email, User.status).all())

    assert_eq(tuple_rows, [("alice@example.com", "active")])


@test(mark="medium")
async def mariadb_runtime_updates_matching_rows() -> None:
    """MariaDB update changes only rows matching the predicate."""

    database = await load_fixture(database_with_update_users())

    async with database.transaction() as tx:
        affected = await tx.execute(
            update(_UpdateUser)
            .set(_UpdateUser.status.to("disabled"))
            .where(_UpdateUser.email.eq("bob@example.com")),
        )
        no_match = await tx.execute(
            update(_UpdateUser)
            .set(_UpdateUser.status.to("archived"))
            .where(_UpdateUser.email.eq("missing@example.com")),
        )

    async with database.transaction() as tx:
        statuses = await tx.fetch_all(
            select(_UpdateUser.email, _UpdateUser.status).all()
        )

    assert_eq(affected, 1)
    assert_eq(no_match, 0)
    assert_eq(
        sorted(statuses),
        [
            ("alice@example.com", "active"),
            ("bob@example.com", "disabled"),
        ],
    )


@test(mark="medium")
async def mariadb_runtime_streams_rows_in_chunks() -> None:
    """MariaDB fetch_chunks streams batches over a server-side cursor."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB streaming coverage."""

        __tablename__ = "issue59_user_stream"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        for index in range(5):
            await tx.execute(insert(User(email=f"user{index}@example.com")))

    async with (
        database.transaction() as tx,
        tx.fetch_chunks(select(User.email).all(), size=2) as stream,
    ):
        batches = [batch async for batch in stream]

    assert_eq([len(batch) for batch in batches], [2, 2, 1])
    assert_eq(
        sorted(email for batch in batches for email in batch),
        [f"user{index}@example.com" for index in range(5)],
    )


@test(mark="medium")
async def mariadb_runtime_closes_stream_cursor_on_early_break() -> None:
    """An early break frees the server-side cursor so the connection stays usable."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB streaming early-exit coverage."""

        __tablename__ = "issue59_user_stream_break"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        for index in range(5):
            await tx.execute(insert(User(email=f"user{index}@example.com")))

    async with database.transaction() as tx:
        async with tx.fetch_chunks(select(User.email).all(), size=2) as stream:
            async for _ in stream:
                break
        # Cursor is closed on stream exit, so the connection serves a follow-up
        # query in the same transaction without a "commands out of sync" error.
        remaining = await tx.fetch_all(select(User.email).all())

    assert_eq(len(remaining), 5)


@test(mark="medium")
async def mariadb_runtime_deletes_filtered_rows() -> None:
    """MariaDB delete removes rows matching the predicate."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB filtered delete coverage."""

        __tablename__ = "issue38_user_filtered_delete"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com", status="active")))
        await tx.execute(insert(User(email="bob@example.com", status="inactive")))

        deleted = await tx.execute(delete(User).where(User.status.eq("inactive")))
        remaining_emails = await tx.fetch_all(select(User.email).all())

    assert_eq(deleted, 1)
    assert_eq(remaining_emails, ["alice@example.com"])


@test(mark="medium")
async def mariadb_runtime_deletes_all_rows() -> None:
    """MariaDB delete all removes every row."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB delete-all coverage."""

        __tablename__ = "issue38_user_delete_all"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com")))
        await tx.execute(insert(User(email="bob@example.com")))

        deleted = await tx.execute(delete(User).all())
        remaining_users = await tx.fetch_all(select(User).all())

    assert_eq(deleted, 2)
    assert_eq(remaining_users, [])


@test(mark="medium")
async def mariadb_execution_errors_preserve_sql_and_params() -> None:
    """MariaDB write failures expose backend SQL and parameter context."""

    class Account[S = Pending](mariadb.Model[S, "Account[Fetched]"]):
        """Table model for MariaDB execution error coverage."""

        __tablename__ = "issue38_account_errors"

        id: Account.Col[int] = mariadb.Integer(primary_key=True)
        email: Account.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([Account]))

    async with database.transaction() as tx:
        await tx.execute(insert(Account(id=1, email="first@example.com")))
        with assert_raises(ExecutionError) as raised:
            await tx.execute(
                insert(Account(id=1, email="duplicate@example.com")),
            )

    assert_eq(
        raised.exception.sql,
        "INSERT INTO `issue38_account_errors` (`id`, `email`) VALUES (%s, %s)",
    )
    assert_eq(raised.exception.params, (1, "duplicate@example.com"))


@test(mark="medium")
async def mariadb_runtime_normalizes_aggregate_result_types() -> None:
    """MariaDB SUM/AVG return DECIMAL; decoding normalizes to int/float.

    This is the cross-backend divergence #109 calls out: SQLite returns an int
    for an integer-column SUM while MariaDB returns DECIMAL. The decode layer
    must make both agree, so SUM over an Integer column is a plain int here too.
    """

    class Sale[S = Pending](mariadb.Model[S, "Sale[Fetched]"]):
        """Integer-amount table for MariaDB aggregate normalization."""

        __tablename__ = "issue109_sale_aggregate"

        id: Sale.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        amount: Sale.Col[int] = mariadb.Integer(nullable=False)

    database = await load_fixture(database_session([Sale]))

    async with database.transaction() as tx:
        empty_sum = await tx.fetch_one(select(Sale.amount.sum()).all())
        await tx.execute(insert(Sale(amount=3)))
        await tx.execute(insert(Sale(amount=4)))
        total = await tx.fetch_one(select(Sale.amount.sum()).all())
        mean = await tx.fetch_one(select(Sale.amount.avg()).all())
        rows = await tx.fetch_one(select(Sale.count_all()).all())

    assert_eq(empty_sum, None)
    assert_eq(total, 7)
    assert isinstance(total, int)
    assert_eq(mean, 3.5)
    assert isinstance(mean, float)
    assert_eq(rows, 2)


@test(mark="medium")
async def mariadb_runtime_groups_and_normalizes_per_group() -> None:
    """A grouped SUM on MariaDB returns one normalized int per group.

    Slice 2 (#112) parity: ``GROUP BY`` collapses rows per key, and the slice-1
    SUM normalization still applies to each group's DECIMAL result.
    """

    class Sale[S = Pending](mariadb.Model[S, "Sale[Fetched]"]):
        """Integer-amount table grouped by region for per-group normalization."""

        __tablename__ = "issue112_sale_grouped"

        id: Sale.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        region: Sale.Col[str] = mariadb.Text(nullable=False)
        amount: Sale.Col[int] = mariadb.Integer(nullable=False)

    database = await load_fixture(database_session([Sale]))

    async with database.transaction() as tx:
        await tx.execute(insert(Sale(region="east", amount=3)))
        await tx.execute(insert(Sale(region="east", amount=4)))
        await tx.execute(insert(Sale(region="west", amount=5)))
        rows = await tx.fetch_all(
            select(Sale.region, Sale.amount.sum())
            .group_by(Sale.region)
            .order_by(Sale.region.asc())
            .all(),
        )

    assert_eq(rows, [("east", 7), ("west", 5)])
    assert all(isinstance(total, int) for _, total in rows)


@test(mark="medium")
async def mariadb_runtime_filters_groups_with_having() -> None:
    """HAVING over an aggregate keeps only qualifying groups on MariaDB.

    Slice 3 (#113) parity: ``HAVING`` filters the grouped rows server-side, and
    the surviving group's DECIMAL SUM still normalizes to ``int``.
    """

    class Sale[S = Pending](mariadb.Model[S, "Sale[Fetched]"]):
        """Integer-amount table grouped by region for HAVING filtering."""

        __tablename__ = "issue113_sale_having"

        id: Sale.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        region: Sale.Col[str] = mariadb.Text(nullable=False)
        amount: Sale.Col[int] = mariadb.Integer(nullable=False)

    database = await load_fixture(database_session([Sale]))

    async with database.transaction() as tx:
        await tx.execute(insert(Sale(region="east", amount=3)))
        await tx.execute(insert(Sale(region="east", amount=4)))
        await tx.execute(insert(Sale(region="west", amount=5)))
        rows = await tx.fetch_all(
            select(Sale.region, Sale.amount.sum())
            .group_by(Sale.region)
            .having(Sale.amount.sum().gt(5))
            .order_by(Sale.region.asc())
            .all(),
        )

    assert_eq(rows, [("east", 7)])
    assert all(isinstance(total, int) for _, total in rows)


@test(mark="medium")
async def mariadb_runtime_filters_with_correlated_subqueries() -> None:
    """Correlated EXISTS and a scalar subquery keep inner/outer params aligned."""

    class Customer[S = Pending](mariadb.Model[S, "Customer[Fetched]"]):
        """Outer table for MariaDB subquery coverage."""

        __tablename__ = "issue118_customer"

        id: Customer.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        country: Customer.Col[str] = mariadb.Text(nullable=False)

    class Purchase[S = Pending](mariadb.Model[S, "Purchase[Fetched]"]):
        """Inner table with a foreign key back to ``Customer``."""

        __tablename__ = "issue118_purchase"

        id: Purchase.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=PENDING_GENERATION,
        )
        customer_id: Purchase.FKCol[Customer, int] = mariadb.ForeignKey(Customer.id)
        amount: Purchase.Col[int] = mariadb.Integer(nullable=False)

    database = await load_fixture(database_session([Customer, Purchase]))

    async with database.transaction() as tx:
        await tx.execute(insert(Customer(country="us")))
        await tx.execute(insert(Customer(country="ca")))
        await tx.execute(insert(Purchase(customer_id=1, amount=30)))
        await tx.execute(insert(Purchase(customer_id=1, amount=40)))

        in_rows = await tx.fetch_all(
            select(Customer.id)
            .where(
                Customer.id.in_subquery(
                    select(Purchase.customer_id).where(Purchase.amount.gt(25)),
                ),
            )
            .order_by(Customer.id.asc()),
        )
        exists_rows = await tx.fetch_all(
            select(Customer.id)
            .where(
                exists(
                    select(Purchase.id).where(
                        Purchase.customer_id.eq_col(Customer.id),
                    ),
                ),
            )
            .order_by(Customer.id.asc()),
        )
        totals = await tx.fetch_all(
            select(
                Customer.id,
                scalar(
                    select(Purchase.amount.sum()).where(
                        Purchase.customer_id.eq_col(Customer.id),
                    ),
                ),
            )
            .all()
            .order_by(Customer.id.asc()),
        )

    assert_eq(in_rows, [1])
    assert_eq(exists_rows, [1])
    assert_eq(totals, [(1, 70), (2, None)])
