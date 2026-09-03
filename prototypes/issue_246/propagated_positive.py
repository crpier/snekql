"""Positive inference probes for the propagated-family prototype."""

from __future__ import annotations

from typing import ClassVar, assert_type

from prototypes.issue_246.propagated_design import (
    Column,
    Fetched,
    InsertQuery,
    MariadbFamily,
    MariadbModel,
    MariadbSelect,
    MariadbWrite,
    Pending,
    SelectQuery,
    SqliteFamily,
    SqliteModel,
    SqliteSelect,
    SqliteWrite,
    Transaction,
    WriteQuery,
    mariadb,
    sqlite,
)


class SqliteUser[S = Pending](SqliteModel[S, "SqliteUser[Fetched]"]):
    id: ClassVar[Column[SqliteFamily, SqliteUser[Pending], int]]


class MariadbUser[S = Pending](MariadbModel[S, "MariadbUser[Fetched]"]):
    id: ClassVar[Column[MariadbFamily, MariadbUser[Pending], int]]


sqlite_model_query = sqlite.select(SqliteUser)
assert_type(
    sqlite_model_query,
    SelectQuery[SqliteFamily, SqliteUser[Pending], SqliteUser[Fetched]],
)
assert_type(
    sqlite.project(SqliteUser.id),
    SelectQuery[SqliteFamily, SqliteUser[Pending], int],
)
sqlite_insert = sqlite.insert(SqliteUser())
assert_type(
    sqlite_insert,
    InsertQuery[SqliteFamily, SqliteUser[Fetched]],
)
assert_type(
    sqlite_insert.returning(),
    WriteQuery[SqliteFamily, SqliteUser[Fetched]],
)

mariadb_model_query = mariadb.select(MariadbUser)
assert_type(
    mariadb_model_query,
    SelectQuery[MariadbFamily, MariadbUser[Pending], MariadbUser[Fetched]],
)
assert_type(
    mariadb.project(MariadbUser.id),
    SelectQuery[MariadbFamily, MariadbUser[Pending], int],
)
mariadb_insert = mariadb.insert(MariadbUser())
assert_type(
    mariadb_insert,
    InsertQuery[MariadbFamily, MariadbUser[Fetched]],
)
assert_type(
    mariadb_insert.returning(),
    WriteQuery[MariadbFamily, MariadbUser[Fetched]],
)


async def sqlite_public_query_annotations_keep_their_family(
    sqlite_transaction: Transaction[SqliteFamily],
    sqlite_query: SqliteSelect[SqliteUser[Fetched]],
    sqlite_write: SqliteWrite[SqliteUser[Fetched]],
) -> None:
    assert_type(
        await sqlite_transaction.fetch_all(sqlite_query),
        list[SqliteUser[Fetched]],
    )
    assert_type(
        await sqlite_transaction.execute(sqlite_write),
        SqliteUser[Fetched],
    )


async def mariadb_public_query_annotations_keep_their_family(
    mariadb_transaction: Transaction[MariadbFamily],
    mariadb_query: MariadbSelect[MariadbUser[Fetched]],
    mariadb_write: MariadbWrite[MariadbUser[Fetched]],
) -> None:
    assert_type(
        await mariadb_transaction.fetch_all(mariadb_query),
        list[MariadbUser[Fetched]],
    )
    assert_type(
        await mariadb_transaction.execute(mariadb_write),
        MariadbUser[Fetched],
    )
