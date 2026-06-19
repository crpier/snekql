"""Backend-neutral migration runner shared by Backend Runtime Adapters.

snekql Migrations are named, hand-authored, ordered raw-SQL changes applied
exactly once and recorded in a snekql-owned Migration History. This module owns
the apply flow — ensure history, compute pending as mapping keys minus applied
names, run each pending body in insertion order, record each success — while
backends answer only how to talk to their Migration History and run raw SQL.

snekql never wraps a migration body and its history row in one transaction (see
ADR 0001): the author owns transactions inside the body, so the body and its
bookkeeping are non-atomic and migrations must be idempotent.

To make concurrent runs safe (see ADR 0002), the whole apply flow — ensure
history, read applied, run pending, record — runs while holding a backend
advisory lock. An instance that loses the race blocks until the holder finishes,
then re-reads the now-complete Migration History and applies only what is still
pending, never re-running an already-applied migration.
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from snekql.errors import MigrationError

logger = logging.getLogger(__name__)


class MigrationBackend(Protocol):
    """Backend seam for Migration History bookkeeping and raw-SQL execution.

    The apply flow lives in `run_migrations`; backends only hold the advisory
    lock that serializes concurrent runs, ensure their history table exists,
    report applied names, run an opaque migration body, and record a name as
    applied.
    """

    def migration_lock(self) -> AbstractAsyncContextManager[None]: ...

    async def ensure_history_table(self) -> None: ...

    async def fetch_applied_names(self) -> set[str]: ...

    async def execute_migration_body(self, sql: str) -> None: ...

    async def record_applied(self, name: str) -> None: ...


async def run_migrations(
    backend: MigrationBackend,
    migrations: dict[str, str],
) -> None:
    """Apply each pending migration exactly once in mapping insertion order.

    The advisory lock wraps the entire flow so a losing instance re-reads the
    completed Migration History after acquiring it and applies nothing already
    applied. The lock is released on success, failure, and disconnect.
    """

    if not migrations:
        return
    async with backend.migration_lock():
        await backend.ensure_history_table()
        applied = await backend.fetch_applied_names()
        for name, sql in migrations.items():
            if name in applied:
                continue
            try:
                await backend.execute_migration_body(sql)
            except Exception as error:
                logger.exception("migration %r failed", name)
                msg = f"migration {name!r} failed"
                raise MigrationError(msg) from error
            await backend.record_applied(name)
            logger.debug("migration %r applied", name)
