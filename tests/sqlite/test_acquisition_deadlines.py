"""SQLite connection opening shares the transaction acquisition deadline."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import patch

from aiosqlite import Connection, Cursor
from anyio import Event, TemporaryDirectory, fail_after, sleep_forever
from snektest import Param, assert_raises, test

from snekql import sqlite


@test(
    [
        Param(value="SELECT 1", name="connectivity"),
        Param(value="PRAGMA journal_mode = WAL", name="settings"),
    ],
    mark="medium",
)
async def lazy_open_obeys_acquisition_deadline(stalled_sql: str) -> None:
    """A stalled connectivity probe times out without leaking admission capacity."""

    original_execute = Connection.execute

    async def stalled_probe(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if sql == stalled_sql:
            await sleep_forever()
        return await original_execute(connection, sql, parameters)

    async with (
        TemporaryDirectory() as directory,
        await sqlite.Database.initialize(
            database=Path(directory) / "deadline.db", pool_size=2
        ) as database,
        database.transaction(),
    ):
        with (
            patch.object(Connection, "execute", stalled_probe),
            fail_after(1),
            assert_raises(sqlite.PoolTimeoutError),
        ):
            async with database.transaction(timeout=0.05):
                pass
        with fail_after(1):
            async with database.transaction():
                pass


@test(mark="medium")
async def timed_out_open_retains_capacity_until_cleanup_finishes() -> None:
    """Slow physical close cannot delay the caller or allow extra pool connections."""

    original_execute = Connection.execute
    original_close = Connection.close
    close_started = Event()
    allow_close = Event()
    timed_out = Event()

    async def stalled_probe(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if sql == "SELECT 1":
            await sleep_forever()
        return await original_execute(connection, sql, parameters)

    async def slow_close(connection: Connection) -> None:
        close_started.set()
        try:
            await allow_close.wait()
        finally:
            await original_close(connection)

    async with (
        TemporaryDirectory() as directory,
        await sqlite.Database.initialize(
            database=Path(directory) / "deadline.db", pool_size=2
        ) as database,
        database.transaction(),
    ):

        async def acquire_connection() -> None:
            with assert_raises(sqlite.PoolTimeoutError):
                async with database.transaction(timeout=0.05):
                    pass
            timed_out.set()

        with (
            patch.object(Connection, "execute", stalled_probe),
            patch.object(Connection, "close", slow_close),
        ):
            pending = asyncio.create_task(acquire_connection())
            try:
                with fail_after(1):
                    await close_started.wait()
                    await timed_out.wait()
                with assert_raises(sqlite.PoolTimeoutError):
                    async with database.transaction(timeout=0.05):
                        pass
            finally:
                allow_close.set()
                await pending
        with fail_after(1):
            async with database.transaction():
                pass


@test(mark="medium")
async def native_cancellation_during_open_recovers_capacity() -> None:
    """Cancelling the caller reaps its opening connection without stranding a slot."""

    original_execute = Connection.execute
    probe_started = Event()

    async def stalled_probe(
        connection: Connection,
        sql: str,
        parameters: Iterable[object] | None = None,
    ) -> Cursor:
        if sql == "SELECT 1":
            probe_started.set()
            await sleep_forever()
        return await original_execute(connection, sql, parameters)

    async with (
        TemporaryDirectory() as directory,
        await sqlite.Database.initialize(
            database=Path(directory) / "deadline.db", pool_size=2
        ) as database,
        database.transaction(),
    ):

        async def acquire_connection() -> None:
            async with database.transaction():
                pass

        with patch.object(Connection, "execute", stalled_probe):
            pending = asyncio.create_task(acquire_connection())
            try:
                with fail_after(1):
                    await probe_started.wait()
            finally:
                pending.cancel()
                with assert_raises(asyncio.CancelledError):
                    await pending
        with fail_after(1):
            async with database.transaction():
                pass
