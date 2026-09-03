"""Public static backend-family conformance probes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from snekql import mariadb, sqlite


class SqliteUser[S = sqlite.Pending](
    sqlite.Model[S, "SqliteUser[sqlite.Fetched]"],
):
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)


class MariadbUser[S = mariadb.Pending](
    mariadb.Model[S, "MariadbUser[mariadb.Fetched]"],
):
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)


if TYPE_CHECKING:

    class SqliteMariaReference[S = sqlite.Pending](
        sqlite.Model[S, "SqliteMariaReference[sqlite.Fetched]"],
    ):
        maria_user_id: sqlite.FKCol[MariadbUser, int] = sqlite.ForeignKey(  # ty: ignore[invalid-type-arguments]
            MariadbUser.id,
        )

    class MariadbSqliteReference[S = mariadb.Pending](
        mariadb.Model[S, "MariadbSqliteReference[mariadb.Fetched]"],
    ):
        sqlite_user_id: mariadb.FKCol[SqliteUser, int] = mariadb.ForeignKey(  # ty: ignore[invalid-type-arguments]
            SqliteUser.id,
        )

    sqlite_model_select: sqlite.Select[SqliteUser[sqlite.Fetched]] = sqlite.select(
        SqliteUser
    )
    sqlite_value_select: sqlite.Select[int] = sqlite.select(SqliteUser.id)
    sqlite_returning: sqlite.Write[SqliteUser[sqlite.Fetched]] = sqlite.insert(
        SqliteUser(id=1)
    ).returning()
    mariadb_model_select: mariadb.Select[MariadbUser[mariadb.Fetched]] = mariadb.select(
        MariadbUser
    )
    mariadb_value_select: mariadb.Select[int] = mariadb.select(MariadbUser.id)
    mariadb_returning: mariadb.Write[MariadbUser[mariadb.Fetched]] = mariadb.insert(
        MariadbUser(id=1)
    ).returning()
    _ = (
        mariadb_model_select,
        mariadb_returning,
        mariadb_value_select,
        sqlite_model_select,
        sqlite_returning,
        sqlite_value_select,
    )

    _ = sqlite.select(MariadbUser)  # ty: ignore[no-matching-overload]
    _ = sqlite.select(MariadbUser.id)  # ty: ignore[no-matching-overload]
    _ = sqlite.insert(MariadbUser(id=1))  # ty: ignore[no-matching-overload]
    _ = sqlite.update(MariadbUser)  # ty: ignore[invalid-argument-type]
    _ = sqlite.delete(MariadbUser)  # ty: ignore[invalid-argument-type]
    _ = sqlite.scaffold([MariadbUser])  # ty: ignore[invalid-argument-type]

    _ = mariadb.select(SqliteUser)  # ty: ignore[no-matching-overload]
    _ = mariadb.select(SqliteUser.id)  # ty: ignore[no-matching-overload]
    _ = mariadb.insert(SqliteUser(id=1))  # ty: ignore[no-matching-overload]
    _ = mariadb.update(SqliteUser)  # ty: ignore[invalid-argument-type]
    _ = mariadb.delete(SqliteUser)  # ty: ignore[invalid-argument-type]
    _ = mariadb.scaffold([SqliteUser])  # ty: ignore[invalid-argument-type]

    _ = sqlite.select(SqliteMariaReference).join(  # ty: ignore[no-matching-overload]
        MariadbUser,
        on=SqliteMariaReference.maria_user_id.references(MariadbUser.id),
    )
    _ = mariadb.select(MariadbSqliteReference).join(  # ty: ignore[no-matching-overload]
        SqliteUser,
        on=MariadbSqliteReference.sqlite_user_id.references(SqliteUser.id),
    )

    async def runtime_rejects_cross_family_queries(
        sqlite_database: sqlite.Database,
        sqlite_transaction: sqlite.Transaction,
        mariadb_database: mariadb.Database,
        mariadb_transaction: mariadb.Transaction,
    ) -> None:
        await sqlite_transaction.fetch_all(
            mariadb.select(MariadbUser).all(),  # ty: ignore[invalid-argument-type]
        )
        await mariadb_transaction.fetch_all(
            sqlite.select(SqliteUser).all(),  # ty: ignore[invalid-argument-type]
        )
        await sqlite_transaction.execute(  # ty: ignore[no-matching-overload]
            mariadb.insert(MariadbUser(id=1)),
        )
        await mariadb_transaction.execute(  # ty: ignore[no-matching-overload]
            sqlite.insert(SqliteUser(id=1)),
        )
        await sqlite_database.verify([SqliteUser])
        await mariadb_database.verify([MariadbUser])
        await sqlite_database.verify(
            [MariadbUser],  # ty: ignore[invalid-argument-type]
        )
        await mariadb_database.verify(
            [SqliteUser],  # ty: ignore[invalid-argument-type]
        )

    async def stored_queries_keep_backend_identity(
        sqlite_transaction: sqlite.Transaction,
        mariadb_select: mariadb.Select[int],
        mariadb_write: mariadb.Write[int],
        sqlite_select: sqlite.Select[int],
        sqlite_write: sqlite.Write[int],
    ) -> None:
        await sqlite_transaction.fetch_all(
            mariadb_select,  # ty: ignore[invalid-argument-type]
        )
        await sqlite_transaction.execute(  # ty: ignore[no-matching-overload]
            mariadb_write,
        )
        sqlite_select = mariadb_select  # ty: ignore[invalid-assignment]
        sqlite_write = mariadb_write  # ty: ignore[invalid-assignment]
        _ = sqlite_select, sqlite_write

    async def databases_reject_cross_family_configuration() -> None:
        await sqlite.Database.initialize(
            mariadb.Config(  # ty: ignore[invalid-argument-type]
                database="app", user="snekql"
            ),
        )
        await mariadb.Database.initialize(
            sqlite.Config(database=Path("app.db")),  # ty: ignore[invalid-argument-type]
        )
        await mariadb.Database.initialize(  # ty: ignore[invalid-argument-type]
            database=Path(":memory:"),
        )
