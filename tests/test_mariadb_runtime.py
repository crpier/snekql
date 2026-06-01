"""MariaDB runtime tracer-bullet integration tests."""

from __future__ import annotations

import subprocess
import sys

from snektest import assert_eq, assert_in, assert_raises, load_fixture, test

from snekql import (
    MISSING,
    Database,
    DatabaseClosedError,
    Pending,
    PoolTimeoutError,
    insert,
    mariadb,
    select,
)
from tests.mariadb_server import MariaDBServer, provide_mariadb_server


class _RollbackSentinelError(Exception):
    """Test-only exception used to force a transaction rollback."""


def _force_rollback() -> None:
    """Raise the sentinel outside the transaction test body."""

    raise _RollbackSentinelError


def _config_from_server(server: MariaDBServer, *, pool_size: int = 5) -> mariadb.Config:
    """Build a MariaDB config for the shared local test server."""

    return mariadb.Config(
        database=server.database,
        host=server.host,
        pool_size=pool_size,
        port=server.port,
        user=server.user,
    )


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

    server = load_fixture(provide_mariadb_server())
    database = await Database.initialize(_config_from_server(server), models=[User])
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
        """Table model for MariaDB transaction lifecycle coverage."""

        __tablename__ = "issue37_user_lifecycle"

        id: User.GenCol[int] = mariadb.Integer(
            primary_key=True,
            auto_increment=True,
            default=MISSING,
        )
        email: User.Col[str] = mariadb.Text(nullable=False)

    server = load_fixture(provide_mariadb_server())
    database = await Database.initialize(
        _config_from_server(server, pool_size=1), models=[User]
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
def mariadb_initialization_without_extra_reports_install_hint() -> None:
    """Runtime initialization explains how to install a missing MariaDB driver."""

    script = """
from __future__ import annotations

import asyncio
import importlib.abc
import sys

import snekql
from snekql import Database, mariadb


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
        _ = await Database.initialize(mariadb.Config(database="app", user="snekql"))
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
