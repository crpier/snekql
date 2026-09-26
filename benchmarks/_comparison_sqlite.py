"""Equivalent SQLite point-read implementations using public driver interfaces."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from time import perf_counter

from aiosqlite import Connection, connect
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from benchmarks._comparison_contract import ReadSession, Record, StreamObservation
from benchmarks._comparison_diagnostics import PoolDiagnostics
from benchmarks._comparison_transactions import core_transaction
from benchmarks._models_sqlite import BenchProfile, BenchUser, BenchWrite
from snekql import sqlite


async def seed(path: Path, rows: int) -> None:
    async with connect(path, isolation_level=None) as connection:
        async with connection.execute("PRAGMA journal_mode = WAL"):
            pass
        async with connection.execute(
            "CREATE TABLE bench_user (id INTEGER PRIMARY KEY, "
            "email TEXT NOT NULL, payload TEXT NOT NULL)"
        ):
            pass
        async with connection.execute(
            "CREATE TABLE bench_profile (user_id INTEGER PRIMARY KEY REFERENCES bench_user(id), payload TEXT NOT NULL)"
        ):
            pass
        async with connection.execute(
            "CREATE TABLE bench_write (id INTEGER PRIMARY KEY, email TEXT NOT NULL, payload TEXT NOT NULL)"
        ):
            pass
        async with connection.execute("BEGIN"):
            pass
        async with connection.executemany(
            "INSERT INTO bench_user VALUES (?, ?, ?)",
            [
                (index, f"user{index}@example.com", "x" * 32)
                for index in range(1, rows + 1)
            ],
        ):
            pass
        async with connection.execute(
            "INSERT INTO bench_profile SELECT id, ? FROM bench_user", ("j" * 32,)
        ):
            pass
        await connection.commit()


@asynccontextmanager
async def _raw_transaction(
    connection: Connection, admission: asyncio.Lock, diagnostics: PoolDiagnostics
) -> AsyncIterator[None]:
    """Keep native commit acknowledgement and rollback ownership inside the lease."""
    started = perf_counter() if diagnostics.active else None
    async with admission:
        if started is not None:
            diagnostics.samples.record(perf_counter() - started)
        async with connection.execute("BEGIN"):
            pass
        try:
            yield
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise


@asynccontextmanager
async def _open_raw(
    path: Path, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    admission = asyncio.Lock()
    async with connect(path, isolation_level=None) as connection:
        for statement in (
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA foreign_keys = ON",
            "PRAGMA busy_timeout = 5000",
        ):
            async with connection.execute(statement):
                pass

        async def read(identity: int, *, joined: bool = False) -> list[Record]:
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.execute(
                    "SELECT bench_user.id, bench_user.email, bench_profile.payload FROM bench_user JOIN bench_profile ON bench_user.id = bench_profile.user_id WHERE bench_user.id = ?"
                    if joined
                    else "SELECT id, email, payload FROM bench_user WHERE id = ?",
                    (identity,),
                ) as cursor,
            ):
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
                connection.execute(
                    "SELECT id, email, payload FROM bench_user ORDER BY id"
                ) as cursor,
            ):
                # aiosqlite delegates to sqlite3.fetchmany(), which returns a list.
                while batch := await cursor.fetchmany(batch_size):  # ty: ignore[truthiness-test-of-iterable]
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
                connection.execute("DELETE FROM bench_write"),
            ):
                pass

        async def bulk(start: int, size: int) -> list[Record]:
            parameters = tuple(
                value
                for identity in range(start, start + size)
                for value in (identity, f"user{identity}@example.com", "x" * 32)
            )
            # Only placeholder count varies; every value is driver-bound.
            sql = "INSERT INTO bench_write (id, email, payload) VALUES " + ", ".join(  # noqa: S608
                ["(?, ?, ?)"] * size
            )
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.execute(sql, parameters),
            ):
                pass
            async with (
                _raw_transaction(connection, admission, diagnostics),
                connection.execute(
                    "SELECT id, email, payload FROM bench_write WHERE id >= ? AND id < ? ORDER BY id",
                    (start, start + size),
                ) as cursor,
            ):
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
        )


@asynccontextmanager
async def _open_snekql(
    path: Path, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    async with await sqlite.Database.initialize(
        sqlite.Config(database=path, pool_size=1, durability="normal"),
        observer=diagnostics.observe if diagnostics.enabled else None,
    ) as database:

        async def read(identity: int, *, joined: bool = False) -> list[Record]:
            if joined:
                query = (
                    sqlite.select(BenchUser)
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
                    sqlite.select(BenchUser)
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
                sqlite.select(BenchUser)
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
                await transaction.execute(sqlite.delete(BenchWrite).all())

        async def bulk(start: int, size: int) -> list[Record]:
            query = sqlite.insert_many(
                BenchWrite,
                [
                    BenchWrite(
                        id=identity,
                        email=f"user{identity}@example.com",
                        payload="x" * 32,
                    )
                    for identity in range(start, start + size)
                ],
            )
            async with database.transaction() as transaction:
                await transaction.execute(query)
            query_read = (
                sqlite.select(BenchWrite)
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
        )


@asynccontextmanager
async def _open_sqlalchemy(
    path: Path, diagnostics: PoolDiagnostics
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
        URL.create("sqlite+aiosqlite", database=str(path)),
        connect_args={"isolation_level": None},
        pool_size=1,
        max_overflow=0,
    )
    try:
        async with engine.connect() as connection:
            for statement in (
                "PRAGMA journal_mode = WAL",
                "PRAGMA synchronous = NORMAL",
                "PRAGMA foreign_keys = ON",
                "PRAGMA busy_timeout = 5000",
            ):
                (await connection.exec_driver_sql(statement)).close()
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
        )
    finally:
        await engine.dispose()


@asynccontextmanager
async def open_reader(
    path: Path, adapter: str, diagnostics: PoolDiagnostics
) -> AsyncIterator[ReadSession]:
    """Own one warmed connection for an explicit adapter selection."""
    factories = {
        "raw": _open_raw,
        "snekql": _open_snekql,
        "sqlalchemy": _open_sqlalchemy,
    }
    async with factories[adapter](path, diagnostics) as session:
        yield session
