"""Expected family rejections for the namespace-facade prototype."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from prototypes.issue_246.facade_design import (
    Column,
    ForeignKeyColumn,
    MariadbConfig,
    MariadbDatabase,
    MariadbModel,
    MariadbSelect,
    MariadbTransaction,
    MariadbWrite,
    Pending,
    SqliteConfig,
    SqliteDatabase,
    SqliteModel,
    SqliteSelect,
    SqliteTransaction,
    SqliteWrite,
    mariadb,
    sqlite,
)


class SqliteUser[S = Pending](SqliteModel[S, "SqliteUser[Pending]"]):
    id: ClassVar[Column[SqliteUser[Pending], int]]


class MariadbUser[S = Pending](MariadbModel[S, "MariadbUser[Pending]"]):
    id: ClassVar[Column[MariadbUser[Pending], int]]


class SqliteMariaReference[S = Pending](
    SqliteModel[S, "SqliteMariaReference[Pending]"],
):
    maria_user_id: ClassVar[
        ForeignKeyColumn[
            SqliteMariaReference[Pending],
            MariadbUser[Pending],
            int,
        ]
    ]


class MariadbSqliteReference[S = Pending](
    MariadbModel[S, "MariadbSqliteReference[Pending]"],
):
    sqlite_user_id: ClassVar[
        ForeignKeyColumn[
            MariadbSqliteReference[Pending],
            SqliteUser[Pending],
            int,
        ]
    ]


_ = sqlite.select(MariadbUser)  # ty: ignore[invalid-argument-type]
_ = sqlite.project(MariadbUser.id)  # ty: ignore[invalid-argument-type]
_ = sqlite.insert(MariadbUser())  # ty: ignore[invalid-argument-type]
_ = sqlite.update(MariadbUser)  # ty: ignore[invalid-argument-type]
_ = sqlite.delete(MariadbUser)  # ty: ignore[invalid-argument-type]
_ = sqlite.foreign_key(MariadbUser.id)  # ty: ignore[invalid-argument-type]
_ = sqlite.scaffold([MariadbUser])  # ty: ignore[invalid-argument-type]

_ = mariadb.select(SqliteUser)  # ty: ignore[invalid-argument-type]
_ = mariadb.project(SqliteUser.id)  # ty: ignore[invalid-argument-type]
_ = mariadb.insert(SqliteUser())  # ty: ignore[invalid-argument-type]
_ = mariadb.update(SqliteUser)  # ty: ignore[invalid-argument-type]
_ = mariadb.delete(SqliteUser)  # ty: ignore[invalid-argument-type]
_ = mariadb.foreign_key(SqliteUser.id)  # ty: ignore[invalid-argument-type]
_ = mariadb.scaffold([SqliteUser])  # ty: ignore[invalid-argument-type]


async def consume_cross_family_queries(
    sqlite_transaction: SqliteTransaction,
    mariadb_transaction: MariadbTransaction,
) -> None:
    await sqlite_transaction.fetch_all(
        mariadb.select(MariadbUser)  # ty: ignore[invalid-argument-type]
    )
    await mariadb_transaction.fetch_all(
        sqlite.select(SqliteUser)  # ty: ignore[invalid-argument-type]
    )
    await sqlite_transaction.execute(
        mariadb.insert(MariadbUser()).returning()  # ty: ignore[invalid-argument-type]
    )
    await mariadb_transaction.execute(
        sqlite.insert(SqliteUser()).returning()  # ty: ignore[invalid-argument-type]
    )

    sqlite_mixed_join = sqlite.select(SqliteMariaReference).join(
        MariadbUser,
        on=SqliteMariaReference.maria_user_id.references(MariadbUser.id),
    )
    await sqlite_transaction.fetch_all(
        sqlite_mixed_join  # ty: ignore[invalid-argument-type]
    )

    mariadb_mixed_join = mariadb.select(MariadbSqliteReference).join(
        SqliteUser,
        on=MariadbSqliteReference.sqlite_user_id.references(SqliteUser.id),
    )
    await mariadb_transaction.fetch_all(
        mariadb_mixed_join  # ty: ignore[invalid-argument-type]
    )


async def cross_public_query_annotations(
    sqlite_transaction: SqliteTransaction,
    mariadb_query: MariadbSelect[int],
    mariadb_write: MariadbWrite[int],
    sqlite_query: SqliteSelect[int],
    sqlite_write: SqliteWrite[int],
) -> None:
    await sqlite_transaction.fetch_all(
        mariadb_query  # ty: ignore[invalid-argument-type]
    )
    await sqlite_transaction.execute(
        mariadb_write  # ty: ignore[invalid-argument-type]
    )
    sqlite_query = mariadb_query  # ty: ignore[invalid-assignment]
    sqlite_write = mariadb_write  # ty: ignore[invalid-assignment]
    _ = sqlite_query, sqlite_write


async def initialize_cross_family_databases() -> None:
    await SqliteDatabase.initialize(
        MariadbConfig()  # ty: ignore[invalid-argument-type]
    )
    await MariadbDatabase.initialize(
        SqliteConfig()  # ty: ignore[invalid-argument-type]
    )
    await MariadbDatabase.initialize(  # ty: ignore[missing-argument]
        database=Path(":memory:")  # ty: ignore[unknown-argument]
    )
