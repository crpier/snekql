"""Positive inference probes for the namespace-facade prototype."""

from __future__ import annotations

from typing import ClassVar, assert_type

from prototypes.issue_246.facade_design import (
    Column,
    Fetched,
    InsertQuery,
    MariadbModel,
    MariadbSelect,
    MariadbTransaction,
    MariadbWrite,
    Pending,
    SelectQuery,
    SqliteModel,
    SqliteSelect,
    SqliteTransaction,
    SqliteWrite,
    WriteQuery,
    mariadb,
    sqlite,
)


class SqliteUser[S = Pending](SqliteModel[S, "SqliteUser[Fetched]"]):
    id: ClassVar[Column[SqliteUser[Pending], int]]


class MariadbUser[S = Pending](MariadbModel[S, "MariadbUser[Fetched]"]):
    id: ClassVar[Column[MariadbUser[Pending], int]]


sqlite_model_query = sqlite.select(SqliteUser)
assert_type(
    sqlite_model_query,
    SelectQuery[SqliteUser[Pending], SqliteUser[Fetched]],
)
assert_type(
    sqlite.project(SqliteUser.id),
    SelectQuery[SqliteUser[Pending], int],
)
sqlite_insert = sqlite.insert(SqliteUser())
assert_type(
    sqlite_insert,
    InsertQuery[SqliteUser[Pending], SqliteUser[Fetched]],
)
assert_type(
    sqlite_insert.returning(),
    WriteQuery[SqliteUser[Pending], SqliteUser[Fetched]],
)
sqlite_stored_select: SqliteSelect[SqliteUser[Fetched]] = sqlite_model_query
sqlite_stored_write: SqliteWrite[SqliteUser[Fetched]] = sqlite_insert.returning()

mariadb_model_query = mariadb.select(MariadbUser)
assert_type(
    mariadb_model_query,
    SelectQuery[MariadbUser[Pending], MariadbUser[Fetched]],
)
assert_type(
    mariadb.project(MariadbUser.id),
    SelectQuery[MariadbUser[Pending], int],
)
mariadb_insert = mariadb.insert(MariadbUser())
assert_type(
    mariadb_insert,
    InsertQuery[MariadbUser[Pending], MariadbUser[Fetched]],
)
assert_type(
    mariadb_insert.returning(),
    WriteQuery[MariadbUser[Pending], MariadbUser[Fetched]],
)
mariadb_stored_select: MariadbSelect[MariadbUser[Fetched]] = mariadb_model_query
mariadb_stored_write: MariadbWrite[MariadbUser[Fetched]] = mariadb_insert.returning()


async def stored_queries_keep_facade_result_inference(
    sqlite_transaction: SqliteTransaction,
    sqlite_query: SqliteSelect[SqliteUser[Fetched]],
    sqlite_write: SqliteWrite[SqliteUser[Fetched]],
    mariadb_transaction: MariadbTransaction,
    mariadb_query: MariadbSelect[MariadbUser[Fetched]],
) -> None:
    assert_type(
        await sqlite_transaction.fetch_all(sqlite_query),
        list[SqliteUser[Fetched]],
    )
    assert_type(
        await sqlite_transaction.execute(sqlite_write),
        SqliteUser[Fetched],
    )
    assert_type(
        await mariadb_transaction.fetch_all(mariadb_query),
        list[MariadbUser[Fetched]],
    )
