"""Compare savepoint recovery using only public snekql operations."""

from contextlib import AsyncExitStack, nullcontext
from traceback import format_exception
from typing import Any

from snekql import mariadb


async def probe(config: mariadb.Config, driver: str, scenario: str) -> dict[str, Any]:
    table = f"prototype_constraint_{driver}"  # Fixed harness driver names only.
    secret = "probe-secret-unique-value"  # noqa: S105 - deliberate noncredential canary
    insert = f"INSERT INTO {table} VALUES (%s, %s, %s, %s)"  # noqa: S608
    no_savepoint = scenario == "constraint-no-savepoint"
    lock_timeout = scenario == "constraint-lock-timeout"
    terminal = no_savepoint or lock_timeout
    invalid_values = {
        "constraint-no-savepoint": (4, secret, 1, 1),
        "constraint-unique": (4, secret, 1, 1),
        "constraint-not-null": (4, None, 1, 1),
        "constraint-check": (4, "invalid", 0, 1),
        "constraint-foreign-insert": (4, "invalid", 1, 999),
    }
    async with AsyncExitStack() as stack:
        database = await stack.enter_async_context(
            await mariadb.Database.initialize(config)
        )
        async with database.transaction() as setup:
            await setup.execute(
                mariadb.raw(
                    f"CREATE TABLE {table}_parent (id INT PRIMARY KEY) ENGINE=InnoDB"
                )
            )
            await setup.execute(
                mariadb.raw(f"INSERT INTO {table}_parent VALUES (1), (2)")  # noqa: S608 - fixed driver names
            )
            await setup.execute(
                mariadb.raw(
                    f"CREATE TABLE {table} (id INT PRIMARY KEY, label VARCHAR(80) NOT NULL UNIQUE, "
                    f"amount INT NOT NULL CHECK (amount > 0), parent INT NOT NULL, "
                    f"FOREIGN KEY(parent) REFERENCES {table}_parent(id)) ENGINE=InnoDB"
                )
            )
        if lock_timeout:
            lock_database = await stack.enter_async_context(
                await mariadb.Database.initialize(config)
            )
            blocker = await stack.enter_async_context(lock_database.transaction())
            await blocker.fetch_one(
                mariadb.raw(
                    f"SELECT id FROM {table}_parent WHERE id = 2 FOR UPDATE"  # noqa: S608
                )
            )
        transaction = database.transaction()
        category = code = None
        redacted = False
        traceback_redacted = False
        blocked = False
        async with transaction:
            before = await transaction.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id")
            )
            await transaction.execute(mariadb.raw(insert, params=(1, secret, 1, 1)))
            try:
                async with (
                    nullcontext() if no_savepoint else transaction.begin_nested()
                ):
                    await transaction.execute(
                        mariadb.raw(insert, params=(2, "inner", 1, 1))
                    )
                    if lock_timeout:
                        await transaction.fetch_one(
                            mariadb.raw(
                                f"SELECT id FROM {table}_parent WHERE id = 2 FOR UPDATE WAIT 1"  # noqa: S608
                            )
                        )
                    elif scenario == "constraint-foreign-delete":
                        await transaction.execute(
                            mariadb.raw(f"DELETE FROM {table}_parent WHERE id = 1")  # noqa: S608 - fixed driver names
                        )
                    else:
                        await transaction.execute(
                            mariadb.raw(insert, params=invalid_values[scenario])
                        )
            except mariadb.ExecutionError as error:
                if error.failure is not None:
                    category, code = error.failure.category, error.failure.code
                redacted = secret not in str(error) and secret not in repr(error)
                traceback_redacted = secret not in "".join(format_exception(error))
            if terminal:
                try:
                    await transaction.fetch_one(mariadb.raw("SELECT 42 AS answer"))
                except mariadb.DatabaseRuntimeError:
                    blocked = True
            else:
                await transaction.execute(
                    mariadb.raw(insert, params=(3, "after", 1, 1))
                )
        async with database.transaction() as verification:
            after = await verification.fetch_one(
                mariadb.raw("SELECT CONNECTION_ID() AS id")
            )
            rows = await verification.fetch_all(
                mariadb.raw(f"SELECT id FROM {table} ORDER BY id")  # noqa: S608 - fixed driver names
            )
        return {
            "blocked": blocked,
            "category": category,
            "code": code,
            "error_redacted": redacted,
            "traceback_redacted": traceback_redacted,
            "same_connection": before["id"] == after["id"],
            "ids": [row["id"] for row in rows],
            "commit_outcome": transaction.commit_outcome,
        }
