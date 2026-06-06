"""MariaDB runtime tracer-bullet integration tests."""

from __future__ import annotations

import subprocess
import sys

from snektest import assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import (
    MISSING,
    Database,
    DatabaseClosedError,
    ExecutionError,
    Pending,
    PoolTimeoutError,
    delete,
    insert,
    mariadb,
    select,
    update,
)
from tests.logging_helpers import NULL_LOGGER
from tests.mariadb_server import TemporaryMariaDBServer, provide_mariadb_server


class _RollbackSentinelError(Exception):
    """Test-only exception used to force a transaction rollback."""


def _force_rollback() -> None:
    """Raise the sentinel outside the transaction test body."""

    raise _RollbackSentinelError


def _config_from_server(
    server: TemporaryMariaDBServer, *, pool_size: int = 5
) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return server.config(pool_size=pool_size)


@test(mark="medium")
async def mariadb_runtime_creates_schema_and_round_trips_model_rows() -> None:
    """A minimal MariaDB Database can create, insert, select, and close."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Table model for the first MariaDB runtime tracer bullet."""

        __tablename__ = "issue37_user_round_trip"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server), models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            fetched_user = await transaction.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
    finally:
        await database.close()

    assert fetched_user is not None
    assert_eq(fetched_user.email, "alice@example.com")
    assert isinstance(fetched_user.id, int)


@test(mark="medium")
async def mariadb_runtime_covers_rollback_pool_timeout_and_close() -> None:
    """The initial MariaDB adapter handles transaction and pool lifecycle."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        __tablename__ = "issue37_user_lifecycle"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server, pool_size=1), models=[User]
    )
    try:
        try:
            async with database.transaction() as transaction:
                await transaction.execute(insert(User(email="rolled-back@example.com")))
                _force_rollback()
        except _RollbackSentinelError:
            pass

        async with database.transaction() as transaction:
            rolled_back_user = await transaction.fetch_one(
                select(User).where(User.email.eq("rolled-back@example.com")),
            )
            assert_eq(rolled_back_user, None)

        async with database.transaction(timeout=0.5):
            with assert_raises(PoolTimeoutError):
                async with database.transaction(timeout=0.01):
                    pass
    finally:
        await database.close()

    with assert_raises(DatabaseClosedError):
        _ = database.transaction()


@test(mark="medium")
async def mariadb_runtime_executes_the_full_query_surface() -> None:
    """MariaDB supports result shapes, filters, ordering, updates, and deletes."""

    class User[S = Pending](mariadb.Model[S, "User[object]"]):
        """Table model for MariaDB query surface coverage."""

        __tablename__ = "issue38_user_query_surface"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)
        status: User.Col[str] = mariadb.Text(nullable=False)
        tenant_id: User.Col[int] = mariadb.Integer(nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server), models=[User]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(
                insert(
                    User(email="charlie@example.com", status="inactive", tenant_id=1)
                )
            )
            await transaction.execute(
                insert(User(email="alice@example.com", status="active", tenant_id=1))
            )
            await transaction.execute(
                insert(User(email="bob@example.com", status="active", tenant_id=2))
            )

            scalar_rows = await transaction.fetch_all(
                select(User.email)
                .where(User.tenant_id.eq(1) & User.status.eq("active"))
                .order_by(User.email.asc())
                .limit(1)
                .offset(0),
            )
            tuple_rows = await transaction.fetch_all(
                select(User.email, User.status)
                .where(User.tenant_id.eq(1))
                .order_by(User.email.asc())
                .limit(1)
                .offset(1),
            )

            await transaction.execute(
                update(User)
                .set(User.status.to("disabled"))
                .where(User.email.eq("bob@example.com")),
            )
            updated_status = await transaction.fetch_one(
                select(User.status).where(User.email.eq("bob@example.com")),
            )

            await transaction.execute(delete(User).where(User.status.eq("inactive")))
            deleted_user = await transaction.fetch_one(
                select(User).where(User.email.eq("charlie@example.com")),
            )

            await transaction.execute(delete(User).all())
            remaining_users = await transaction.fetch_all(select(User).all())
    finally:
        await database.close()

    assert_eq(scalar_rows, ["alice@example.com"])
    assert_eq(tuple_rows, [("charlie@example.com", "inactive")])
    assert_eq(updated_status, "disabled")
    assert_eq(deleted_user, None)
    assert_eq(remaining_users, [])


@test(mark="medium")
async def mariadb_execution_errors_preserve_sql_and_params() -> None:
    """MariaDB write failures expose backend SQL and parameter context."""

    class Account[S = Pending](mariadb.Model[S, "Account[object]"]):
        """Table model for MariaDB execution error coverage."""

        __tablename__ = "issue38_account_errors"

        id: Account.Col[int] = mariadb.Integer(primary_key=True)
        email: Account.Col[str] = mariadb.Text(nullable=False)

    server = await load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        NULL_LOGGER, _config_from_server(server), models=[Account]
    )
    try:
        async with database.transaction() as transaction:
            await transaction.execute(insert(Account(id=1, email="first@example.com")))
            with assert_raises(ExecutionError) as raised:
                await transaction.execute(
                    insert(Account(id=1, email="duplicate@example.com")),
                )
    finally:
        await database.close()

    assert_in("INSERT INTO `issue38_account_errors`", raised.exception.sql)
    assert_in("%s", raised.exception.sql)
    assert_eq(raised.exception.params, (1, "duplicate@example.com"))


@test(mark="medium")
def mariadb_initialization_without_extra_reports_install_hint() -> None:
    """Runtime initialization explains how to install a missing MariaDB driver."""

    script = """
from __future__ import annotations

import asyncio
import importlib.abc
import sys

import snekql
from snekql import Database, mariadb
from tests.logging_helpers import NULL_LOGGER


class BlockAiomysql(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "aiomysql" or fullname.startswith("aiomysql."):
            raise ModuleNotFoundError("No module named 'aiomysql'", name="aiomysql")
        return None


async def main() -> None:
    blocker = BlockAiomysql()
    sys.modules.pop("aiomysql", None)
    sys.meta_path.insert(0, blocker)
    try:
        _ = await Database.initialize(NULL_LOGGER, mariadb.Config(database="app", user="snekql"))
    except snekql.DatabaseRuntimeError as error:
        print(error)
        return
    finally:
        sys.meta_path.remove(blocker)
    raise AssertionError("MariaDB initialization unexpectedly succeeded")


asyncio.run(main())
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("snekql[aiomysql]", result.stdout)
