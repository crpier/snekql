"""MariaDB migration, verification, insert, and read example."""

from __future__ import annotations

from snekql import mariadb
from snekql.mariadb import Database, Fetched, Pending, insert, select


class User[S = Pending](mariadb.Model[S, "User[Fetched]"]):
    """Example MariaDB table model."""

    id: User.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=mariadb.PENDING_GENERATION,
    )
    email: User.Col[str] = mariadb.Text(unique=True)


MIGRATIONS = {
    "0001_create_user": (
        "CREATE TABLE `user` ("
        "`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        "`email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL"
        ") ENGINE=InnoDB"
    ),
    "0002_user_email_unique": (
        "CREATE UNIQUE INDEX `ux_user_email` ON `user` (`email`)"
    ),
}


async def run(config: mariadb.Config) -> None:
    """Apply the committed chain and exercise one transaction."""

    async with await Database.initialize(config) as database:
        await database.migrate(MIGRATIONS)
        await database.verify_migrations(MIGRATIONS)
        await database.verify([User])
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            user = await transaction.fetch_one(select(User).all())
            print(user.email)
