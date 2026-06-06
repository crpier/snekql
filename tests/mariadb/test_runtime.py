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

from snekql import (
    MISSING,
    Database,
    DatabaseClosedError,
    ExecutionError,
    Fetched,
    Pending,
    PoolTimeoutError,
    delete,
    insert,
    mariadb,
    select,
    update,
)
from snekql.model import Table
from tests.helpers import NULL_LOGGER, provide_mariadb_server


class _RollbackSentinelError(Exception):
    """Test-only exception used to force a transaction rollback."""


class _UpdateUser[S = Pending](mariadb.Model[S, "_UpdateUser[Fetched]"]):
    """Table model for MariaDB update coverage."""

    __tablename__ = "issue38_user_update"

    id: _UpdateUser.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
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
    database = await Database.initialize(
        server.config(pool_size=pool_size), logger=NULL_LOGGER, models=models
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
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com")))

    async with database.transaction() as tx:
        fetched_user = await tx.fetch_one(
            select(User).where(User.email.eq("alice@example.com")),
        )

    assert fetched_user is not None
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
            default=MISSING,
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
        rolled_back_user = await tx.fetch_one(
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
            default=MISSING,
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
            default=MISSING,
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
        await tx.execute(
            update(_UpdateUser)
            .set(_UpdateUser.status.to("disabled"))
            .where(_UpdateUser.email.eq("bob@example.com")),
        )

    async with database.transaction() as tx:
        statuses = await tx.fetch_all(
            select(_UpdateUser.email, _UpdateUser.status).all()
        )

    assert_eq(
        sorted(statuses),
        [
            ("alice@example.com", "active"),
            ("bob@example.com", "disabled"),
        ],
    )


@test(mark="medium")
async def mariadb_runtime_deletes_filtered_rows() -> None:
    """MariaDB delete removes rows matching the predicate."""

    class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
        """Table model for MariaDB filtered delete coverage."""

        __tablename__ = "issue38_user_filtered_delete"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com", status="active")))
        await tx.execute(insert(User(email="bob@example.com", status="inactive")))

        await tx.execute(delete(User).where(User.status.eq("inactive")))
        remaining_emails = await tx.fetch_all(select(User.email).all())

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
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    database = await load_fixture(database_session([User]))

    async with database.transaction() as tx:
        await tx.execute(insert(User(email="alice@example.com")))
        await tx.execute(insert(User(email="bob@example.com")))

        await tx.execute(delete(User).all())
        remaining_users = await tx.fetch_all(select(User).all())

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
