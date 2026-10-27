"""Current application: no historical bindings, authoring, or migration ownership."""

from typing import ClassVar

from snekql import mariadb, sqlite


class SQLiteAccount[S = sqlite.Pending](sqlite.Model[S]):
    """Current role representation, independent of historical authoring models."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[sqlite.ReadType[SQLiteAccount[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    role: sqlite.Col[str] = sqlite.Text()


async def use_sqlite(config: sqlite.Config) -> list[tuple[int, str]]:
    """Verify structure separately, write a user, and read current typed values."""
    async with await sqlite.Database.initialize(config) as app:
        await app.verify([SQLiteAccount])
        async with app.transaction() as tx:
            await tx.execute(sqlite.insert(SQLiteAccount(id=3, role="user")))
        async with app.transaction() as tx:
            rows = await tx.fetch_all(
                sqlite.select(SQLiteAccount).order_by(SQLiteAccount.id.asc())
            )
    return [(row.id, row.role) for row in rows]


class MariaDBAccount[S = mariadb.Pending](mariadb.Model[S]):
    """Current role representation, independent of historical authoring models."""

    __tablename__ = "accounts"
    __row_type__: ClassVar[mariadb.ReadType[MariaDBAccount[mariadb.Row]]]
    id: mariadb.Col[int] = mariadb.Integer(primary_key=True)
    role: mariadb.Col[str] = mariadb.Text()


async def use_mariadb(config: mariadb.Config) -> list[tuple[int, str]]:
    """Verify structure separately, write a user, and read current typed values."""
    async with await mariadb.Database.initialize(config) as app:
        await app.verify([MariaDBAccount])
        async with app.transaction() as tx:
            await tx.execute(mariadb.insert(MariaDBAccount(id=3, role="user")))
        async with app.transaction() as tx:
            rows = await tx.fetch_all(
                mariadb.select(MariaDBAccount).order_by(MariaDBAccount.id.asc())
            )
    return [(row.id, row.role) for row in rows]
