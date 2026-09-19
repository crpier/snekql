"""Database-only observations that intentionally bypass both application models."""

from sqlite3 import SQLITE_CONSTRAINT
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine


def expected_data_error(error: BaseException | None, backend: str) -> bool:
    """Do not count connection, SQL syntax, or harness failures as refusals."""
    if backend == "sqlite":
        code = getattr(error, "sqlite_errorcode", 0)
        return isinstance(code, int) and code & 0xFF == SQLITE_CONSTRAINT
    return (
        error is not None
        and bool(error.args)
        and error.args[0] in {1048, 1264, 1292, 1364, 1366, 1406, 4025}
    )


async def inspect_schema(engine: AsyncEngine, backend: str) -> dict[str, Any]:
    """Keep the live DDL, not only model metadata."""
    async with engine.connect() as connection:
        installed = await connection.exec_driver_sql(
            "SELECT sql FROM sqlite_schema WHERE name='orders'"
            if backend == "sqlite"
            else "SHOW CREATE TABLE orders"
        )
        return {
            "installed_ddl": list(installed.one()),
            "checks": await connection.run_sync(
                lambda sync: inspect(sync).get_check_constraints("orders")
            ),
            "columns": await connection.run_sync(
                lambda sync: inspect(sync).get_columns("orders")
            ),
        }


async def observe_raw(engine: AsyncEngine, backend: str) -> dict[str, Any]:
    """Each raw write rolls back before the next case."""
    statements = {
        "defaults": "INSERT INTO orders (price_cents,quantity) VALUES (123,1)",
        "zero_quantity": "INSERT INTO orders (price_cents,quantity) VALUES (123,0)",
        "negative_cents": "INSERT INTO orders (price_cents,quantity) VALUES (-1,1)",
        "overflow_cents": "INSERT INTO orders (price_cents,quantity) VALUES (10000000000,1)",
        "overflow_quantity": "INSERT INTO orders (price_cents,quantity) VALUES (123,2147483648)",
        "fractional_cents": "INSERT INTO orders (price_cents,quantity) VALUES (1.5,1)",
        "string_quantity": "INSERT INTO orders (price_cents,quantity) VALUES (123,'1')",
        "null_timestamp": "INSERT INTO orders (price_cents,quantity,created_at) VALUES (123,1,NULL)",
        "null_status": "INSERT INTO orders (price_cents,quantity,status) VALUES (123,1,NULL)",
        "invalid_timestamp": "INSERT INTO orders (price_cents,quantity,created_at) VALUES (123,1,'not-a-date')",
    }
    observations: dict[str, Any] = {}
    async with engine.connect() as connection:
        for name, statement in statements.items():
            record: dict[str, Any] = {"sql": statement}
            try:
                await connection.exec_driver_sql(statement)
            except DBAPIError as e:
                if not expected_data_error(e.orig, backend):
                    raise
                record.update(outcome="rejected", error=str(e.orig))
            else:
                if backend == "mariadb":
                    record["warnings"] = [
                        list(row)
                        for row in await connection.exec_driver_sql("SHOW WARNINGS")
                    ]
                record["rows"] = [
                    list(row)
                    for row in await connection.exec_driver_sql(
                        "SELECT price_cents,quantity,status,created_at FROM orders"
                    )
                ]
                record["types"] = [
                    [type(cell).__name__ for cell in row] for row in record["rows"]
                ]
                record["outcome"] = "accepted"
            finally:
                await connection.rollback()
            observations[name] = record
    return observations
