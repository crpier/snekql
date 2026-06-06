"""Shared MariaDB server fixture for integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from snektest import session_fixture

from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    temporary_mariadb_server,
)

_RESET_DATABASE_SQL = """
SET SESSION group_concat_max_len = 1000000;
SET FOREIGN_KEY_CHECKS = 0;
SELECT GROUP_CONCAT(CONCAT('`', REPLACE(TABLE_NAME, '`', '``'), '`'))
INTO @snekql_tables_to_drop
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_TYPE = 'BASE TABLE';
SET @snekql_drop_tables = IF(
    @snekql_tables_to_drop IS NULL,
    'DO 0',
    CONCAT('DROP TABLE ', @snekql_tables_to_drop)
);
PREPARE snekql_drop_tables_statement FROM @snekql_drop_tables;
EXECUTE snekql_drop_tables_statement;
DEALLOCATE PREPARE snekql_drop_tables_statement;
SET FOREIGN_KEY_CHECKS = 1;
"""


async def reset_mariadb_database(server: TemporaryMariaDBServer) -> None:
    """Drop all application tables from the shared MariaDB test database."""

    _ = await server.run_sql(_RESET_DATABASE_SQL)


@session_fixture()
async def provide_mariadb_server() -> AsyncGenerator[TemporaryMariaDBServer]:
    """Provide a local MariaDB server for medium integration tests."""

    async with temporary_mariadb_server(
        data_directory=Path(".snektest/mariadb-data"),
        transports={"tcp"},
    ) as server:
        await reset_mariadb_database(server)
        yield server
