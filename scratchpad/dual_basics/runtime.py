"""Research facade only: native code still owns connections and transactions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from snekql import sqlite as native

from scratchpad.dual_backends.sqlite import Transaction


class Database:
    """Hide the experiment's transaction translation, not a replacement runtime.

    Only initialization, context lifetime, migrations, and default transactions
    are exposed. Native configuration, observation, savepoints, and transaction
    options are not covered by this facade.
    """

    def __init__(self, database: native.Database) -> None:
        self._native: native.Database = database

    async def __aenter__(self) -> Self:
        await self._native.__aenter__()
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._native.__aexit__(exception_type, exception, traceback)

    @classmethod
    async def initialize(cls, *, database: Path | Literal[":memory:"]) -> Self:
        return cls(await native.Database.initialize(database=database))

    async def migrate(self, migrations: dict[str, str]) -> native.MigrationResult:
        return await self._native.migrate(migrations)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        async with self._native.transaction() as transaction:
            yield Transaction(transaction)
