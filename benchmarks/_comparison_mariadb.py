"""Owned-server MariaDB comparisons with identical session and result policies."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from functools import partial
from time import perf_counter
from typing import cast

from aiomysql import Connection, SSCursor, connect
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from benchmarks._comparison_contract import (
    ComparisonError,
    ReadSession,
    Record,
    StreamObservation,
)
from benchmarks._comparison_diagnostics import PoolDiagnostics
from benchmarks._comparison_transactions import core_transaction
from benchmarks._models_mariadb import BenchProfile, BenchUser, BenchWrite
from snekql import mariadb

POLICY = {
    "autocommit": 0,
    "read_only": 0,
    "charset": "utf8mb4",
    "isolation": "REPEATABLE-READ",
    "sql_mode": "STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO",
    "time_zone": "+00:00",
    "foreign_key_checks": 1,
    "check_constraint_checks": 1,
    "unique_checks": 1,
    "transport": "tcp-loopback",
}
"""Common application policy; backend setup is outside timed transactions."""

_SETTINGS = (
    "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ",
    "SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'",
    "SET time_zone = '+00:00'",
    "SET SESSION foreign_key_checks = 1",
    "SET SESSION check_constraint_checks = 1",
    "SET SESSION unique_checks = 1",
)


_POLICY_QUERY = """SELECT
    @@SESSION.character_set_connection AS charset,
    @@SESSION.tx_isolation AS isolation,
    @@SESSION.sql_mode AS sql_mode,
    @@SESSION.time_zone AS time_zone,
    @@SESSION.foreign_key_checks AS foreign_key_checks,
    @@SESSION.check_constraint_checks AS check_constraint_checks,
    @@SESSION.unique_checks AS unique_checks,
    @@SESSION.autocommit AS autocommit,
    @@SESSION.tx_read_only AS read_only
"""


def _verified_policy(cells: Sequence[object]) -> dict[str, object]:
    """Refuse to compare connections whose effective policies differ."""
    observed = dict(
        zip(
            (
                "charset",
                "isolation",
                "sql_mode",
                "time_zone",
                "foreign_key_checks",
                "check_constraint_checks",
                "unique_checks",
                "autocommit",
                "read_only",
            ),
            cells,
            strict=True,
        )
    )
    observed["sql_mode"] = sorted(str(observed["sql_mode"]).split(","))
    expected: dict[str, object] = {
        name: value for name, value in POLICY.items() if name != "transport"
    }
    expected["sql_mode"] = sorted(str(expected["sql_mode"]).split(","))
    if observed != expected:
        message = (
            "MariaDB comparison connection policy differs from the declared contract"
        )
        raise ComparisonError(message)
    return observed


@asynccontextmanager
async def _raw_transaction(
    connection: Connection, admission: asyncio.Lock, diagnostics: PoolDiagnostics
) -> AsyncIterator[None]:
    """Keep native commit acknowledgement and rollback ownership inside the lease."""
    started = perf_counter() if diagnostics.active else None
    async with admission:
        if started is not None:
            diagnostics.samples.record(perf_counter() - started)
        await connection.begin()
        try:
            yield
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise


@asynccontextmanager
async def _connection(config: mariadb.Config) -> AsyncIterator[Connection]:
    # aiomysql's untyped awaitable returns its documented Connection type.
    connection = cast(
        "Connection",
        await connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            db=config.database,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=30,
        ),
    )
    try:
        async with connection.cursor() as cursor:
            for statement in _SETTINGS:
                await cursor.execute(statement)
        yield connection
    finally:
        await connection.ensure_closed()


@asynccontextmanager
async def _open_raw(
    config: mariadb.Config, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    admission = asyncio.Lock()
    async with _connection(config) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(_POLICY_QUERY)
            policy = _verified_policy(await cursor.fetchone())
        await connection.rollback()

        async def read(identity: int, *, joined: bool = False) -> list[Record]:
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.cursor() as cursor,
            ):
                await cursor.execute(
                    "SELECT bench_user.id, bench_user.email, bench_profile.payload FROM bench_user JOIN bench_profile ON bench_user.id = bench_profile.user_id WHERE bench_user.id = %s"
                    if joined
                    else "SELECT id, email, payload FROM bench_user WHERE id = %s",
                    (identity,),
                )
                return [
                    Record.model_validate(
                        {"id": row[0], "email": row[1], "payload": row[2]}
                    )
                    for row in await cursor.fetchall()
                ]

        async def stream(batch_size: int) -> StreamObservation:
            observation = StreamObservation()
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.cursor(SSCursor) as cursor,
            ):
                await cursor.execute(
                    "SELECT id, email, payload FROM bench_user ORDER BY id"
                )
                while batch := await cursor.fetchmany(batch_size):
                    observation.consume(
                        Record.model_validate(
                            {"id": row[0], "email": row[1], "payload": row[2]}
                        )
                        for row in batch
                    )
                    await asyncio.sleep(0)
            return observation

        async def reset_bulk() -> None:
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.cursor() as cursor,
            ):
                await cursor.execute("DELETE FROM bench_write")

        async def bulk(start: int, size: int) -> list[Record]:
            parameters = tuple(
                value
                for identity in range(start, start + size)
                for value in (identity, f"user{identity}@example.com", "x" * 32)
            )
            # Only placeholder count varies; every value is driver-bound.
            sql = "INSERT INTO bench_write (id, email, payload) VALUES " + ", ".join(  # noqa: S608
                ["(%s, %s, %s)"] * size
            )
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.cursor() as cursor,
            ):
                await cursor.execute(sql, parameters)
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.cursor() as cursor,
            ):
                await cursor.execute(
                    "SELECT id, email, payload FROM bench_write WHERE id >= %s AND id < %s ORDER BY id",
                    (start, start + size),
                )
                return [
                    Record.model_validate(
                        {"id": row[0], "email": row[1], "payload": row[2]}
                    )
                    for row in await cursor.fetchall()
                ]

        yield ReadSession(
            bulk=bulk,
            reset_bulk=reset_bulk,
            join=partial(read, joined=True),
            read=read,
            stream=stream,
            policy=policy,
        )


@asynccontextmanager
async def _open_snekql(
    config: mariadb.Config, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    async with await mariadb.Database.initialize(
        config, observer=diagnostics.observe if diagnostics.enabled else None
    ) as database:
        async with database.transaction() as transaction:
            observed = await transaction.fetch_one(mariadb.raw(_POLICY_QUERY))
            policy = _verified_policy(list(observed.values()))

        async def read(identity: int, *, joined: bool = False) -> list[Record]:
            if joined:
                query = (
                    mariadb.select(BenchUser)
                    .join(BenchProfile, on=BenchUser.id.eq_col(BenchProfile.user_id))
                    .project(
                        Record,
                        id=BenchUser.id,
                        email=BenchUser.email,
                        payload=BenchProfile.payload,
                    )
                    .where(BenchUser.id.eq(identity))
                )
            else:
                query = (
                    mariadb.select(BenchUser)
                    .project(
                        Record,
                        id=BenchUser.id,
                        email=BenchUser.email,
                        payload=BenchUser.payload,
                    )
                    .where(BenchUser.id.eq(identity))
                )
            async with database.transaction() as transaction:
                return await transaction.fetch_all(query)

        async def stream(batch_size: int) -> StreamObservation:
            observation = StreamObservation()
            query = (
                mariadb.select(BenchUser)
                .project(
                    Record,
                    id=BenchUser.id,
                    email=BenchUser.email,
                    payload=BenchUser.payload,
                )
                .all()
                .order_by(BenchUser.id.asc())
            )
            async with (
                database.transaction() as transaction,
                transaction.fetch_chunks(query, size=batch_size) as chunks,
            ):
                async for batch in chunks:
                    observation.consume(batch)
                    await asyncio.sleep(0)
            return observation

        async def reset_bulk() -> None:
            async with database.transaction() as transaction:
                await transaction.execute(mariadb.delete(BenchWrite).all())

        async def bulk(start: int, size: int) -> list[Record]:
            query = mariadb.insert(
                [
                    BenchWrite(
                        id=identity,
                        email=f"user{identity}@example.com",
                        payload="x" * 32,
                    )
                    for identity in range(start, start + size)
                ]
            )
            async with database.transaction() as transaction:
                await transaction.execute(query)
            query_read = (
                mariadb.select(BenchWrite)
                .project(
                    Record,
                    id=BenchWrite.id,
                    email=BenchWrite.email,
                    payload=BenchWrite.payload,
                )
                .where(BenchWrite.id.gte(start) & BenchWrite.id.lt(start + size))
                .order_by(BenchWrite.id.asc())
            )
            async with database.transaction() as transaction:
                return await transaction.fetch_all(query_read)

        yield ReadSession(
            bulk=bulk,
            reset_bulk=reset_bulk,
            join=partial(read, joined=True),
            read=read,
            stream=stream,
            policy=policy,
        )


@asynccontextmanager
async def _open_sqlalchemy(
    config: mariadb.Config, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    table = Table(
        "bench_user",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("email", String),
        Column("payload", String),
    )
    profile = Table(
        "bench_profile",
        table.metadata,
        Column("user_id", Integer),
        Column("payload", String),
    )
    writes = Table(
        "bench_write",
        table.metadata,
        Column("id", Integer, primary_key=True),
        Column("email", String),
        Column("payload", String),
    )
    engine = create_async_engine(
        URL.create(
            "mysql+aiomysql",
            username=config.user,
            password=config.password,
            host=config.host,
            port=config.port,
            database=config.database,
            query={"charset": "utf8mb4"},
        ),
        pool_size=1,
        max_overflow=0,
        connect_args={"autocommit": False},
    )
    try:
        async with engine.connect() as connection:
            for statement in _SETTINGS:
                (await connection.exec_driver_sql(statement)).close()
            result = await connection.exec_driver_sql(_POLICY_QUERY)
            policy = _verified_policy(tuple(result.one()))
            result.close()
            await connection.commit()

        async def read(identity: int, *, joined: bool = False) -> list[Record]:
            query = (
                select(table.c.id, table.c.email, profile.c.payload)
                .join_from(table, profile, table.c.id == profile.c.user_id)
                .where(table.c.id == identity)
                if joined
                else select(table).where(table.c.id == identity)
            )
            async with core_transaction(engine, diagnostics) as connection:
                result = await connection.execute(query)
                records = [
                    Record.model_validate(dict(row)) for row in result.mappings().all()
                ]
                result.close()
            return records

        async def stream(batch_size: int) -> StreamObservation:
            observation = StreamObservation()
            query = select(table).order_by(table.c.id)
            async with (
                core_transaction(engine, diagnostics) as connection,
                connection.stream(
                    query,
                    execution_options={
                        "yield_per": batch_size,
                        "max_row_buffer": batch_size,
                    },
                ) as result,
            ):
                async for batch in result.mappings().partitions(batch_size):
                    observation.consume(
                        Record.model_validate(dict(row)) for row in batch
                    )
                    await asyncio.sleep(0)
            return observation

        async def reset_bulk() -> None:
            async with core_transaction(engine, diagnostics) as connection:
                (await connection.execute(delete(writes))).close()

        async def bulk(start: int, size: int) -> list[Record]:
            query = insert(writes).values(
                [
                    {
                        "id": identity,
                        "email": f"user{identity}@example.com",
                        "payload": "x" * 32,
                    }
                    for identity in range(start, start + size)
                ]
            )
            async with core_transaction(engine, diagnostics) as connection:
                (await connection.execute(query)).close()
            query_read = (
                select(writes)
                .where(writes.c.id >= start, writes.c.id < start + size)
                .order_by(writes.c.id)
            )
            async with core_transaction(engine, diagnostics) as connection:
                result = await connection.execute(query_read)
                records = [
                    Record.model_validate(dict(row)) for row in result.mappings().all()
                ]
                result.close()
            return records

        yield ReadSession(
            bulk=bulk,
            reset_bulk=reset_bulk,
            join=partial(read, joined=True),
            read=read,
            stream=stream,
            policy=policy,
        )
    finally:
        await engine.dispose()


async def seed(config: mariadb.Config, rows: int) -> dict[str, object]:
    """Populate the private server and record actual native durability settings."""
    async with _connection(config) as connection, connection.cursor() as cursor:
        await cursor.execute(
            "CREATE TABLE bench_user (id INTEGER PRIMARY KEY, "
            "email VARCHAR(255) NOT NULL, payload VARCHAR(255) NOT NULL) "
            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        await cursor.execute(
            "CREATE TABLE bench_profile (user_id INTEGER PRIMARY KEY, payload VARCHAR(255) NOT NULL, "
            "FOREIGN KEY (user_id) REFERENCES bench_user(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        await cursor.execute(
            "CREATE TABLE bench_write (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL, "
            "payload VARCHAR(255) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        await connection.begin()
        await cursor.executemany(
            "INSERT INTO bench_user VALUES (%s, %s, %s)",
            [
                (index, f"user{index}@example.com", "x" * 32)
                for index in range(1, rows + 1)
            ],
        )
        await cursor.execute(
            "INSERT INTO bench_profile SELECT id, %s FROM bench_user", ("j" * 32,)
        )
        await connection.commit()
        await cursor.execute(
            "SELECT VERSION(), @@innodb_flush_log_at_trx_commit, "
            "@@sync_binlog, @@log_bin, @@innodb_page_size, @@SESSION.tx_isolation"
        )
        metadata = await cursor.fetchone()
        return dict(
            zip(
                (
                    "version",
                    "innodb_flush_log_at_trx_commit",
                    "sync_binlog",
                    "log_bin",
                    "innodb_page_size",
                    "seed_session_isolation",
                ),
                metadata,
                strict=True,
            )
        )


@asynccontextmanager
async def open_reader(
    config: mariadb.Config, adapter: str, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    """Own one warmed connection for an explicit adapter selection."""
    factories = {
        "raw": _open_raw,
        "snekql": _open_snekql,
        "sqlalchemy": _open_sqlalchemy,
    }
    async with factories[adapter](config, diagnostics) as session:
        yield session
