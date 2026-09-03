"""Current production inference that both candidate designs must preserve."""

from __future__ import annotations

from typing import assert_type

from snekql import mariadb, sqlite


class SqliteUser[S = sqlite.Pending](
    sqlite.Model[S, "SqliteUser[sqlite.Fetched]"],
):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class MariadbUser[S = mariadb.Pending](
    mariadb.Model[S, "MariadbUser[mariadb.Fetched]"],
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


async def sqlite_result_inference(transaction: sqlite.Transaction) -> None:
    assert_type(
        await transaction.fetch_all(sqlite.select(SqliteUser).all()),
        list[SqliteUser[sqlite.Fetched]],
    )
    assert_type(
        await transaction.fetch_all(sqlite.select(SqliteUser.id).all()),
        list[int],
    )
    assert_type(
        await transaction.execute(sqlite.insert(SqliteUser(id=1)).returning()),
        SqliteUser[sqlite.Fetched],
    )


async def mariadb_result_inference(transaction: mariadb.Transaction) -> None:
    assert_type(
        await transaction.fetch_all(mariadb.select(MariadbUser).all()),
        list[MariadbUser[mariadb.Fetched]],
    )
    assert_type(
        await transaction.fetch_all(mariadb.select(MariadbUser.id).all()),
        list[int],
    )
    assert_type(
        await transaction.execute(mariadb.insert(MariadbUser(id=1)).returning()),
        MariadbUser[mariadb.Fetched],
    )
