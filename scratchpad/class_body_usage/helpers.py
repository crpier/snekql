"""Generic helper controls distinguish nominal base parameters from query results."""

from typing import Any

from snekql import sqlite


def insert_generic[Read: sqlite.Model[Any, Any]](
    pending: sqlite.Model[sqlite.Pending, Read],
) -> sqlite.Write[Read]:
    """Existing nominal-base annotations erase the new class-body evidence."""
    return sqlite.insert(pending).returning()


async def execute_write[Result](
    transaction: sqlite.Transaction,
    command: sqlite.Write[Result],
) -> Result:
    """Query-oriented helpers retain the result without naming a model base."""
    return await transaction.execute(command)
