"""Public-driver cancellation probes for an owned, disposable MariaDB server."""

import asyncio
from contextlib import suppress
from importlib import import_module
from importlib.metadata import version
from typing import Any


async def _wait_for_sleep(observer: Any, identity: int) -> None:
    """Wait for server-side execution, not a guessed client scheduling delay."""
    async with asyncio.timeout(10):
        while True:
            async with observer.cursor() as cursor:
                await cursor.execute(
                    "SELECT STATE FROM information_schema.PROCESSLIST WHERE ID = %s",
                    (identity,),
                )
                row = await cursor.fetchone()
            if row and row[0] == "User sleep":
                return
            await asyncio.sleep(0.01)


async def probe(  # noqa: PLR0915 - keep the cancellation/lease sequence explicit
    driver: Any, options: dict[str, object], scenario: str
) -> dict[str, object]:
    """Cancel a server-observed query, then verify pool replacement and rollback."""
    pool = await driver.create_pool(minsize=1, maxsize=1, **options)
    observer = None
    task = None
    try:
        async with asyncio.timeout(30):
            observer = await driver.connect(**options)
            # Driver names come only from the harness's fixed module list.
            table = f"cancellation_write_{driver.__name__}"
            async with observer.cursor() as cursor:
                await cursor.execute(
                    f"CREATE TABLE {table} (id INT PRIMARY KEY) ENGINE=InnoDB"
                )
            async with pool.acquire() as connection:
                server_version = connection.get_server_info()
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT CONNECTION_ID()")
                    before = (await cursor.fetchone())[0]
                await connection.begin()
                cursor = await connection.cursor()
                await cursor.execute(f"INSERT INTO {table} VALUES (1)")  # noqa: S608 - fixed driver names
                await cursor.close()
                first_identity = None
                if scenario in {"cancel-fetch", "cancel-close"}:
                    cursor = await connection.cursor(
                        import_module(f"{driver.__name__}.cursors").SSCursor
                    )
                    # A large first row flushes the wire before the second row
                    # enters SLEEP. No ORDER BY/materialization barrier is used.
                    await cursor.execute(
                        "SELECT seq, REPEAT('x', 65536), IF(seq = 2, SLEEP(5), 0) "
                        "FROM seq_1_to_2"
                    )
                    first = await cursor.fetchone()
                    if first != (1, "x" * 65536, 0):
                        message = "Streaming setup did not deliver the first row"
                        raise RuntimeError(message)
                    first_identity = first[0]
                    operation = (
                        cursor.close()
                        if scenario == "cancel-close"
                        else cursor.fetchone()
                    )
                else:
                    cursor = await connection.cursor()
                    operation = cursor.execute("SELECT SLEEP(5)")
                started = asyncio.Event()

                async def pending() -> None:
                    started.set()
                    await operation

                task = asyncio.create_task(pending())
                try:
                    await started.wait()
                    await _wait_for_sleep(observer, before)
                    if task.done():
                        message = "Operation completed before cancellation barrier"
                        raise RuntimeError(message)
                    task.cancel()
                    cancelled = False
                    try:
                        await task
                    except asyncio.CancelledError:
                        cancelled = True
                    driver_closed = (
                        not connection.connected
                        if driver.__name__ == "asyncmy"
                        else connection.closed
                    )
                finally:
                    # Snapshot the driver's own action above, then enforce our
                    # fail-closed policy even if a future driver leaves it open.
                    connection.close()
            async with pool.acquire() as connection, connection.cursor() as cursor:
                await cursor.execute("SELECT CONNECTION_ID(), 42")
                after, answer = await cursor.fetchone()
                await cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed driver names
                visible_writes = (await cursor.fetchone())[0]
                # Reusing the same unique key also checks that the old write's
                # lock is released, not merely hidden by MVCC. No server KILL
                # or explicit rollback assists this normal path.
                await cursor.execute(f"INSERT INTO {table} VALUES (1)")  # noqa: S608 - fixed driver names
                await cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed driver names
                recovered_writes = (await cursor.fetchone())[0]
            return {
                "driver": driver.__name__,
                "version": version(driver.__name__),
                "server": server_version,
                "cancelled": cancelled,
                "first_identity": first_identity,
                "driver_closed": driver_closed,
                "same_connection": before == after,
                "visible_writes": visible_writes,
                "recovered_writes": recovered_writes,
                "answer": answer,
            }
    finally:
        if task is not None:
            task.cancel()
            # The main path observes task errors; cleanup must still release
            # the observer and pool if the operation failed before the barrier.
            with suppress(asyncio.CancelledError, Exception):
                await task
        if observer is not None:
            observer.close()
        pool.terminate()
        await pool.wait_closed()
