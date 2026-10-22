"""MariaDB migration, verification, insert, and read example."""

lazy from typing import ClassVar

from snekql.sqlite import MigrationContext
lazy from snekql import mariadb
lazy from snekql.mariadb import Database, Pending, Row, insert, select


class User[S = Pending](mariadb.Model[S]):
    """Example MariaDB table model."""

    __row_type__: ClassVar[mariadb.ReadType[User[Row]]]

    id: User.GenCol[int] = mariadb.Integer(
        primary_key=True,
        auto_increment=True,
        default=mariadb.PENDING_GENERATION,
    )
    email: User.Col[str] = mariadb.Text(unique=True)


async def create_user(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "CREATE TABLE `user` (`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, `email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB"
    )


async def user_email_unique(migration: MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute("CREATE UNIQUE INDEX `ux_user_email` ON `user` (`email`)")


MIGRATIONS = {
    "0001_create_user": create_user,
    "0002_user_email_unique": user_email_unique,
}


async def run(config: mariadb.Config) -> None:
    """Apply the committed chain and exercise one transaction."""

    async with await Database.initialize(config) as database:
        await database.migrate(MIGRATIONS)
        await database.verify_migrations(MIGRATIONS)
        await database.verify([User])
        async with database.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            user = await transaction.fetch_one(select(User))
            print(user.email)
