"""Two real execution paths under the same scheduling protocol."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from os import fsdecode
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import URL, event, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from research.concurrency import mariadb_models, sqlite_models
from research.concurrency.observations import ObservationError
from research.concurrency.sqlalchemy_models import models
from snekql.testing.mariadb import temporary_mariadb_server


@dataclass
class Runtime:
    """Scheduling adapter; library-specific writes remain visible here."""

    backend: str
    database: Any
    engine: AsyncEngine
    entry: Any
    library: str
    namespace: Any
    statements: list[dict[str, Any]] = field(default_factory=list)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Acquire an independent transaction, committing only on clean exit."""
        if self.library == "snekql":
            async with self.database.transaction() as transaction:
                if self.backend == "sqlite":
                    await transaction.fetch_one(
                        self.namespace.raw("PRAGMA busy_timeout=100")
                    )
                yield transaction
        else:
            async with (
                AsyncSession(self.engine, expire_on_commit=False) as session,
                session.begin(),
            ):
                yield session

    async def read(self, transaction: Any) -> dict[str, int]:
        if self.library == "snekql":
            row = await transaction.fetch_one(
                self.namespace.select(self.entry).where(self.entry.id.eq(1))
            )
        else:
            row = (
                await transaction.scalars(select(self.entry).where(self.entry.id == 1))
            ).one()
        return {"quantity": row.quantity, "revision": row.revision}

    async def write(
        self, transaction: Any, strategy: str, observed: dict[str, int]
    ) -> int:
        """Stale assignment has no guard. CAS both compares and advances revision."""
        if self.library == "snekql":
            if strategy == "atomic":
                sql = (
                    "UPDATE counter SET quantity=quantity-1, revision=revision+1 WHERE id=:id AND quantity>0"
                    if self.backend == "sqlite"
                    else "UPDATE counter SET quantity=quantity-1, revision=revision+1 WHERE id=%(id)s AND quantity>0"
                )
                query = self.namespace.raw(sql, params={"id": 1})
                self.statements.append({"path": "raw", "sql": sql, "params": {"id": 1}})
            else:
                assignments = [
                    self.entry.quantity.to(
                        observed["quantity"]
                        if strategy == "noop"
                        else observed["quantity"] - 1
                    )
                ]
                predicates = [self.entry.id.eq(1)]
                if strategy == "cas":
                    assignments.append(self.entry.revision.to(observed["revision"] + 1))
                    predicates.append(self.entry.revision.eq(observed["revision"]))
                query = (
                    self.namespace.update(self.entry)
                    .set(*assignments)
                    .where(*predicates)
                )
                compiled = query.compile()
                self.statements.append(
                    {
                        "path": "compiled_builder",
                        "sql": compiled.sql,
                        "params": compiled.params,
                    }
                )
            rowcount = await transaction.execute(query)
        else:
            query = update(self.entry).where(self.entry.id == 1)
            if strategy == "atomic":
                query = query.where(self.entry.quantity > 0).values(
                    quantity=self.entry.quantity - 1, revision=self.entry.revision + 1
                )
            elif strategy == "cas":
                query = query.where(self.entry.revision == observed["revision"]).values(
                    quantity=observed["quantity"] - 1, revision=observed["revision"] + 1
                )
            else:
                query = query.values(
                    quantity=observed["quantity"]
                    if strategy == "noop"
                    else observed["quantity"] - 1
                )
            rowcount = (await transaction.execute(query)).rowcount
        if not isinstance(rowcount, int) or rowcount not in (0, 1):
            message = (
                f"single-row update returned an unsupported rowcount: {rowcount!r}"
            )
            raise ObservationError(message)
        return rowcount

    async def fresh(self) -> dict[str, int]:
        async with self.transaction() as transaction:
            return await self.read(transaction)

    async def controls(self, transaction: Any) -> dict[str, Any]:
        """Inspect the actual borrowed session after a table read established policy."""
        sql = (
            "SELECT sqlite_version() AS version, (SELECT journal_mode FROM pragma_journal_mode) AS journal_mode, (SELECT timeout FROM pragma_busy_timeout) AS busy_timeout, (SELECT foreign_keys FROM pragma_foreign_keys) AS foreign_keys"
            if self.backend == "sqlite"
            else "SELECT VERSION() AS version, CONNECTION_ID() AS connection_id, @@tx_isolation AS isolation, @@innodb_snapshot_isolation AS snapshot_isolation, @@innodb_lock_wait_timeout AS lock_wait_timeout, @@innodb_rollback_on_timeout AS rollback_on_timeout, @@time_zone AS time_zone, @@sql_mode AS sql_mode, @@collation_database AS collation, @@default_storage_engine AS engine"
        )
        if self.library == "snekql":
            return await transaction.fetch_one(self.namespace.raw(sql))
        controls = dict((await transaction.execute(text(sql))).mappings().one())
        if self.backend == "sqlite":
            connection = await transaction.connection()
            proxy = await connection.get_raw_connection()
            controls["session_in_transaction"] = transaction.in_transaction()
            controls["driver_in_transaction"] = proxy.driver_connection.in_transaction
        return controls

    async def reset(self) -> None:
        """Seed outside the schedule; no worker transactions remain open here."""
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("DELETE FROM counter")
            await connection.exec_driver_sql(
                "INSERT INTO counter (id, quantity, revision) VALUES (1, 10, 1)"
            )


@asynccontextmanager
async def _engine(
    url: URL, backend: str, sqlite_begin: str
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url, pool_size=2, max_overflow=0)

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        if backend == "sqlite" and sqlite_begin == "explicit":
            connection.isolation_level = None
        cursor = connection.cursor()
        try:
            if backend == "sqlite":
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=100")
            else:
                cursor.execute("SET SESSION time_zone='+00:00'")
                cursor.execute(
                    "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
                )
        finally:
            cursor.close()

    if backend == "sqlite" and sqlite_begin == "explicit":

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN")

    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def _database(
    engine: AsyncEngine, declarations: Any, config: Any, library: str, backend: str
) -> AsyncIterator[Runtime]:
    if library == "snekql":
        async with await declarations.db.Database.initialize(config) as database:
            await database.migrate(
                {"001_counter": declarations.db.scaffold([declarations.Counter])}
            )
            yield Runtime(
                backend,
                database,
                engine,
                declarations.Counter,
                library,
                declarations.db,
            )
    else:
        entry = models()
        async with engine.begin() as connection:
            await connection.run_sync(entry.metadata.create_all)
        adapter = Runtime(backend, None, engine, entry, library, None)

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture(
            _connection: Any,
            _cursor: Any,
            statement: str,
            parameters: Any,
            _context: Any,
            _executemany: bool,  # noqa: FBT001 - SQLAlchemy event signature.
        ) -> None:
            if statement.startswith("UPDATE counter"):
                adapter.statements.append(
                    {"path": "driver_statement", "sql": statement, "params": parameters}
                )

        yield adapter


@asynccontextmanager
async def runtime(
    backend: str,
    library: str,
    sqlite_begin: str = "explicit",
    *,
    snapshot_isolation: bool = True,
) -> AsyncIterator[Runtime]:
    """Only owned temporary files and socket-only MariaDB servers are accepted."""
    if backend == "sqlite":
        directory = await asyncio.to_thread(
            TemporaryDirectory, prefix="snekql-concurrency-"
        )
        try:
            path = Path(fsdecode(directory.name)) / "study.sqlite"
            async with (
                _engine(
                    URL.create("sqlite+aiosqlite", database=str(path)),
                    backend,
                    sqlite_begin,
                ) as engine,
                _database(
                    engine,
                    sqlite_models,
                    sqlite_models.db.Config(
                        database=path,
                        pool_size=2,
                        busy_max_retries=0,
                        operation_timeout=5,
                    ),
                    library,
                    backend,
                ) as adapter,
            ):
                yield adapter
        finally:
            await asyncio.to_thread(directory.cleanup)
    else:
        async with (
            temporary_mariadb_server(
                server_args=(
                    "--character-set-server=utf8mb4",
                    "--collation-server=utf8mb4_bin",
                    "--default-storage-engine=InnoDB",
                    "--transaction-isolation=REPEATABLE-READ",
                    "--innodb-lock-wait-timeout=1",
                    "--innodb-snapshot-isolation=ON"
                    if snapshot_isolation
                    else "--innodb-snapshot-isolation=OFF",
                )
            ) as server,
            _engine(
                URL.create(
                    "mysql+aiomysql",
                    username=server.user,
                    database=server.database,
                    query={
                        "unix_socket": str(server.socket_path),
                        "charset": "utf8mb4",
                    },
                ),
                backend,
                sqlite_begin,
            ) as engine,
            _database(
                engine,
                mariadb_models,
                replace(server.config(pool_size=2), operation_timeout=5),
                library,
                backend,
            ) as adapter,
        ):
            yield adapter
