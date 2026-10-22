"""Minimal runnable snekql application."""

lazy import asyncio
lazy from typing import ClassVar

lazy from snekql import sqlite
lazy from snekql.sqlite import Database, Pending, Row, insert, select


class User[S = Pending](sqlite.Model[S]):
    """Example table model used by the basic application."""

    __row_type__: ClassVar[sqlite.ReadType[User[Row]]]

    id: sqlite.GenCol[int] = sqlite.Integer(
        primary_key=True,
        auto_increment=True,
        default=sqlite.PENDING_GENERATION,
    )
    email: sqlite.Col[str] = sqlite.Text(unique=True)
    created_at: sqlite.GenCol[sqlite.UtcDatetime] = sqlite.Text(
        default=sqlite.CurrentTimestamp
    )


async def create_user(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        'CREATE TABLE "user" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "email" TEXT NOT NULL, "created_at" TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%fZ\', \'now\'))) STRICT'
    )


async def user_email_unique(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute('CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")')


async def create_user_temporal(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        'CREATE TABLE "user_temporal" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "email" TEXT NOT NULL, "created_at" TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%f\', \'now\') || \'000Z\')) STRICT'
    )


async def copy_user_temporal(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute(
        "INSERT INTO user_temporal (id, email, created_at) SELECT id, email, CASE WHEN length(created_at) = 24 AND strftime('%Y-%m-%dT%H:%M:%fZ', created_at) = created_at THEN substr(created_at, 1, 23) || '000Z' ELSE NULL END FROM user"
    )


async def drop_old_user(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute('DROP TABLE "user"')


async def rename_user_temporal(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute('ALTER TABLE "user_temporal" RENAME TO "user"')


async def restore_user_email_unique(migration: sqlite.MigrationContext) -> None:
    """Apply one reviewed revision."""
    await migration.execute('CREATE UNIQUE INDEX "ux_user_email" ON "user" ("email")')


MIGRATIONS = {
    "0001_create_user": create_user,
    "0002_user_email_unique": user_email_unique,
    "0003_create_user_temporal": create_user_temporal,
    "0004_copy_user_temporal": copy_user_temporal,
    "0005_drop_old_user": drop_old_user,
    "0006_rename_user_temporal": rename_user_temporal,
    "0007_restore_user_email_unique": restore_user_email_unique,
}


async def main() -> None:
    """Create a table, insert a row, and read it back."""

    async with await Database.initialize(sqlite.Config(database=":memory:")) as db:
        await db.migrate(MIGRATIONS)
        await db.verify_migrations(MIGRATIONS)
        await db.verify([User])
        async with db.transaction() as transaction:
            await transaction.execute(insert(User(email="alice@example.com")))
            user = await transaction.fetch_one(
                select(User).where(User.email.eq("alice@example.com")),
            )
            print(user.email)


if __name__ == "__main__":
    asyncio.run(main())
