"""Declaration checks must not evaluate consumer type-only annotations."""

from typing import TYPE_CHECKING

from snektest import assert_eq, test

from snekql import sqlite

if TYPE_CHECKING:
    from snekql.sqlite import MigrationContext


@test(mark="fast")
async def type_only_context_import_does_not_prevent_execution() -> None:
    """Python's deferred annotations need not be importable at runtime."""

    async def revision(context: MigrationContext) -> None:
        await context.execute("SELECT 1")

    async with await sqlite.Database.initialize(database=":memory:") as database:
        result = await database.migrate({"001": revision})
    assert_eq(result.applied, ("001",))
