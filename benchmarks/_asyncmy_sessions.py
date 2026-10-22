"""Session initialization/replacement observations through public transactions."""

import asyncio
from typing import Any

from anyio import wait_all_tasks_blocked

from snekql import mariadb

_SESSION = """SELECT CONNECTION_ID() AS id,
    @@SESSION.time_zone AS time_zone,
    @@SESSION.sql_mode AS sql_mode,
    @@SESSION.foreign_key_checks AS foreign_key_checks,
    @@SESSION.check_constraint_checks AS check_constraint_checks,
    @@SESSION.unique_checks AS unique_checks,
    @@SESSION.autocommit AS autocommit,
    @@SESSION.character_set_connection AS character_set_connection"""


async def probe(config: mariadb.Config) -> dict[str, Any]:
    async with await mariadb.Database.initialize(config) as database:
        sessions = []
        async with database.transaction() as first:
            sessions.append(dict(await first.fetch_one(mariadb.raw(_SESSION))))
        async with database.transaction() as reused:
            sessions.append(dict(await reused.fetch_one(mariadb.raw(_SESSION))))
        rejected = False
        async with database.transaction() as unsafe:
            try:
                async with unsafe.fetch_chunks(
                    mariadb.raw("SELECT seq FROM seq_1_to_64; SELECT 2"), size=1
                ) as stream:
                    await anext(stream)
            except mariadb.RawResultShapeError:
                rejected = True
        async with database.transaction() as replacement:
            sessions.append(dict(await replacement.fetch_one(mariadb.raw(_SESSION))))
        stats = database.pool_stats()
        result = {
            "sessions": sessions,
            "reused": sessions[0]["id"] == sessions[1]["id"],
            "replaced": sessions[1]["id"] != sessions[2]["id"],
            "extra_results_rejected": rejected,
            "occupied": stats.occupied,
            "waiters": stats.waiters,
            "discarded_connections": stats.discarded_connections,
        }
    result["pool_state_after_close"] = database.pool_stats().state
    return result


async def mutation_probe(config: mariadb.Config) -> dict[str, Any]:
    """Characterize raw session mutations, not permission to bypass required policy."""
    query = mariadb.raw(
        "SELECT CONNECTION_ID() AS id, @@SESSION.time_zone AS time_zone, "
        "@snekql_session_probe AS marker"
    )
    async with await mariadb.Database.initialize(config) as database:
        async with database.transaction() as first:
            await first.execute(mariadb.raw("SET SESSION time_zone = '+05:30'"))
            await first.execute(mariadb.raw("SET @snekql_session_probe = 42"))
            within = dict(await first.fetch_one(query))
        async with database.transaction() as reused:
            after = dict(await reused.fetch_one(query))
        rejected = False
        async with database.transaction() as unsafe:
            try:
                async with unsafe.fetch_chunks(
                    mariadb.raw("SELECT seq FROM seq_1_to_64; SELECT 2"), size=1
                ) as stream:
                    await anext(stream)
            except mariadb.RawResultShapeError:
                rejected = True
        async with database.transaction() as replacement:
            fresh = dict(await replacement.fetch_one(query))
        return {
            "within_lease": within,
            "next_lease": after,
            "replacement": fresh,
            "reused": within["id"] == after["id"],
            "replaced": after["id"] != fresh["id"],
            "extra_results_rejected": rejected,
        }


async def shutdown_probe(config: mariadb.Config) -> dict[str, Any]:
    """Real close deadline held by a live public transaction, no driver patches."""
    database = await mariadb.Database.initialize(config)
    close_error = None
    new_work_error = None
    closed_work_error = None
    try:
        transaction = database.transaction()
        async with transaction:
            # Keep a real lease occupied while close exhausts its configured budget.
            await transaction.fetch_one(mariadb.raw("SELECT 1 AS ready"))
            try:
                await database.close()
            except mariadb.DatabaseCloseTimeoutError as error:
                close_error = type(error).__name__
            after_failure = database.pool_stats()
            try:
                async with database.transaction():
                    pass
            except mariadb.DatabaseClosingError as error:
                new_work_error = type(error).__name__
            answer = await transaction.fetch_one(mariadb.raw("SELECT 42 AS answer"))
        await database.close()
        await database.close()  # Successful shutdown is idempotent.
        try:
            async with database.transaction():
                pass
        except mariadb.DatabaseClosedError as error:
            closed_work_error = type(error).__name__
        final = database.pool_stats()
        return {
            "close_error": close_error,
            "new_work_error": new_work_error,
            "closed_work_error": closed_work_error,
            "state_after_failure": after_failure.state,
            "occupied_after_failure": after_failure.occupied,
            "active_answer": answer["answer"],
            "commit_outcome": transaction.commit_outcome,
            "final_state": final.state,
            "occupied": final.occupied,
            "waiters": final.waiters,
        }
    finally:
        await database.close()


async def cancelled_shutdown_probe(config: mariadb.Config) -> dict[str, Any]:
    database = await mariadb.Database.initialize(config)
    tasks: list[asyncio.Task[None]] = []
    cancel_error = None
    new_work_error = None
    try:
        transaction = database.transaction()
        async with transaction:
            await transaction.fetch_one(mariadb.raw("SELECT 1 AS ready"))
            cancelled = asyncio.create_task(database.close())
            tasks.append(cancelled)
            await wait_all_tasks_blocked()
            if database.pool_stats().state != "closing" or cancelled.done():
                message = "shutdown did not block on the held public lease"
                raise RuntimeError(message)
            cancelled.cancel()
            try:
                await cancelled
            except asyncio.CancelledError as error:
                cancel_error = type(error).__name__
            joining = asyncio.create_task(database.close())
            tasks.append(joining)
            await wait_all_tasks_blocked()
            pending = not joining.done()
            try:
                async with database.transaction():
                    pass
            except mariadb.DatabaseClosingError as error:
                new_work_error = type(error).__name__
            answer = await transaction.fetch_one(mariadb.raw("SELECT 42 AS answer"))
        await joining
        await database.close()
        final = database.pool_stats()
        return {
            "cancel_error": cancel_error,
            "concurrent_close_pending": pending,
            "new_work_error": new_work_error,
            "active_answer": answer["answer"],
            "commit_outcome": transaction.commit_outcome,
            "final_state": final.state,
            "occupied": final.occupied,
            "waiters": final.waiters,
        }
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await database.close()
