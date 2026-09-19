"""Owned disposable databases; no caller-supplied connection URLs."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from os import fsdecode
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import URL, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from research.loading import mariadb_models, sqlite_models
from research.loading.mariadb_app import Application as MariadbApplication
from research.loading.sqlalchemy_app import Application as OrmApplication
from research.loading.sqlalchemy_models import Base
from research.loading.sqlite_app import Application as SqliteApplication
from research.loading.telemetry import Statement, capture
from research.loading.views import LoadingStudyError
from snekql import mariadb, sqlite
from snekql.testing.mariadb import temporary_mariadb_server

type LoadingApplication = SqliteApplication | MariadbApplication | OrmApplication


@dataclass
class Study:
    """The application and its external observation channels share one lifetime."""

    app: LoadingApplication
    controls: dict[str, Any]
    ddl: dict[str, str]
    statements: list[Statement]


SEED = (
    "INSERT INTO customer (id,name) VALUES (1,'Ada'),(2,'Ben')",
    "INSERT INTO product (id,name,current_cents) VALUES (1,'Widget',9999),(2,'Gadget',8888),(3,'Other',7777)",
    "INSERT INTO purchase (id,customer_id,placed_seq) VALUES (101,1,30),(102,1,30),(103,1,20),(104,1,10),(201,2,40)",
    "INSERT INTO line (id,order_id,product_id,quantity,unit_cents) VALUES (1001,101,1,2,125),(1002,101,2,1,300),(1003,101,1,3,110),(1004,102,1,1,125),(1005,104,2,1,10),(1006,104,2,1,20),(1007,104,2,1,30),(1008,104,2,1,40),(1009,104,2,1,50),(2001,201,3,7,100)",
)


def _configure(engine: AsyncEngine, backend: str) -> None:
    """Apply connection policies to every physical connection, including BEGIN."""

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        try:
            if backend == "sqlite":
                connection.isolation_level = None
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
            else:
                cursor.execute("SET time_zone='+00:00'")
                cursor.execute(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
                )
        finally:
            cursor.close()

    if backend == "sqlite":

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN")


async def _describe(
    app: LoadingApplication, engine: AsyncEngine, backend: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """Read installed schema and actual runtime controls outside measured reads."""
    ddl: dict[str, str] = {}
    async with engine.connect() as connection:
        for table in ("customer", "product", "purchase", "line"):
            if backend == "sqlite":
                ddl[table] = (
                    await connection.execute(
                        text("SELECT sql FROM sqlite_master WHERE name=:name"),
                        {"name": table},
                    )
                ).scalar_one()
            else:
                # Table names are the fixed declarations above, never request input.
                ddl[table] = (
                    await connection.exec_driver_sql(f"SHOW CREATE TABLE `{table}`")
                ).one()[1]
    control_sql = (
        "SELECT sqlite_version() AS version, (SELECT journal_mode FROM pragma_journal_mode) AS journal_mode, (SELECT foreign_keys FROM pragma_foreign_keys) AS foreign_keys"
        if backend == "sqlite"
        else "SELECT VERSION() AS version, @@tx_isolation AS isolation, @@innodb_snapshot_isolation AS snapshot_isolation, @@time_zone AS time_zone, @@sql_mode AS sql_mode, @@foreign_key_checks AS foreign_keys, @@default_storage_engine AS engine"
    )
    if isinstance(app, SqliteApplication):
        async with app.database.transaction() as transaction:
            controls = await transaction.fetch_one(sqlite.raw(control_sql))
    elif isinstance(app, MariadbApplication):
        async with app.database.transaction() as transaction:
            controls = await transaction.fetch_one(mariadb.raw(control_sql))
    else:
        async with engine.connect() as connection:
            controls = dict(
                (await connection.execute(text(control_sql))).mappings().one()
            )
    return controls, ddl


@asynccontextmanager
async def application(backend: str, strategy: str) -> AsyncIterator[Study]:
    """Seed independently of application reads, then close all owned resources."""
    if backend not in ("sqlite", "mariadb") or strategy not in (
        "snekql",
        "selectin",
        "joined",
        "per-order",
    ):
        message = "unsupported configuration"
        raise LoadingStudyError(message)
    async with AsyncExitStack() as stack:
        directory = await asyncio.to_thread(TemporaryDirectory)
        stack.push_async_callback(asyncio.to_thread, directory.cleanup)
        path = Path(fsdecode(directory.name))
        maria_config: mariadb.Config | None = None
        if backend == "mariadb":
            server = await stack.enter_async_context(
                temporary_mariadb_server(
                    data_directory=path / "mariadb",
                    server_args=(
                        "--transaction-isolation=REPEATABLE-READ",
                        "--character-set-server=utf8mb4",
                        "--collation-server=utf8mb4_bin",
                    ),
                )
            )
            maria_config = server.config(pool_size=2)
            url = URL.create(
                "mysql+aiomysql",
                username=server.user,
                password=server.password,
                database=server.database,
                query={"unix_socket": str(server.socket_path), "charset": "utf8mb4"},
            )
        else:
            url = URL.create("sqlite+aiosqlite", database=str(path / "study.db"))
        engine = create_async_engine(url, pool_size=2, max_overflow=0)
        stack.push_async_callback(engine.dispose)

        _configure(engine, backend)

        app: LoadingApplication
        if strategy != "snekql":
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            app = OrmApplication(engine, strategy)
        elif maria_config is None:
            database = await stack.enter_async_context(
                await sqlite.Database.initialize(
                    sqlite.Config(database=path / "study.db", pool_size=2)
                )
            )
            await database.migrate(
                {
                    f"create_{index}": sqlite.scaffold([model])
                    for index, model in enumerate(
                        (
                            sqlite_models.Customer,
                            sqlite_models.Product,
                            sqlite_models.Purchase,
                            sqlite_models.Line,
                        )
                    )
                }
            )
            app = SqliteApplication(database)
        else:
            maria_database = await stack.enter_async_context(
                await mariadb.Database.initialize(maria_config)
            )
            await maria_database.migrate(
                {
                    f"create_{index}": mariadb.scaffold([model])
                    for index, model in enumerate(
                        (
                            mariadb_models.Customer,
                            mariadb_models.Product,
                            mariadb_models.Purchase,
                            mariadb_models.Line,
                        )
                    )
                }
            )
            app = MariadbApplication(maria_database)
        async with engine.begin() as connection:
            for statement in SEED:
                await connection.exec_driver_sql(statement)
        controls, ddl = await _describe(app, engine, backend)
        statements: list[Statement] = []

        with capture(statements, engine):
            yield Study(app=app, controls=controls, ddl=ddl, statements=statements)
