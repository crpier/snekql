"""The packaged example upgrades existing timestamp text without rewriting history."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from snektest import assert_eq, fixture, load_fixture, test

from snekql import sqlite
from snekql.examples.basic import MIGRATIONS, User


@fixture
async def provide_legacy_clock_database() -> AsyncGenerator[sqlite.Database]:
    async with await sqlite.Database.initialize(database=":memory:") as database:
        await database.migrate(dict(list(MIGRATIONS.items())[:2]))
        async with database.transaction() as transaction:
            await transaction.execute(
                sqlite.raw(
                    "INSERT INTO user (id, email, created_at) VALUES "
                    "(1, 'earlier', '2026-01-01T00:00:00.123Z'), "
                    "(2, 'later', '2026-01-01T00:00:00.124Z')"
                )
            )
        yield database


@test(mark="medium")
async def migration_restores_sub_millisecond_range_semantics() -> None:
    """A bound between old millisecond rows excludes the earlier instant."""
    database = await load_fixture(provide_legacy_clock_database())

    await database.migrate(MIGRATIONS)
    await database.verify([User])
    async with database.transaction() as transaction:
        identifiers = await transaction.fetch_all(
            sqlite.select(User.id)
            .where(
                User.created_at.gte(
                    sqlite.UtcDatetime(
                        datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)
                    )
                )
            )
            .order_by(User.id.asc())
        )

    assert_eq(identifiers, [2])
