"""Backend-neutral migration runner shared by Backend Runtime Adapters.

snekql Migrations are named, hand-authored, ordered raw-SQL changes applied
exactly once and recorded in a snekql-owned Migration History. This module owns
the apply flow — ensure history, compute pending as mapping keys minus applied
names, run each pending body in insertion order, record each success — while
backends answer only how to talk to their Migration History and run raw SQL.

snekql never wraps a migration body and its history row in one transaction (see
ADR 0001): the author owns transactions inside the body, so the body and its
bookkeeping are non-atomic and migrations must be idempotent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from snekql.errors import MigrationError

if TYPE_CHECKING:
    from snekql.structured_logging import ResolvedStructuredLogger


class MigrationBackend(Protocol):
    """Backend seam for Migration History bookkeeping and raw-SQL execution.

    The apply flow lives in `run_migrations`; backends only ensure their history
    table exists, report applied names, run an opaque migration body, and record
    a name as applied.
    """

    async def ensure_history_table(self) -> None: ...

    async def fetch_applied_names(self) -> set[str]: ...

    async def execute_migration_body(self, sql: str) -> None: ...

    async def record_applied(self, name: str) -> None: ...


async def run_migrations(
    backend: MigrationBackend,
    migrations: dict[str, str],
    *,
    logger: ResolvedStructuredLogger,
) -> None:
    """Apply each pending migration exactly once in mapping insertion order."""

    if not migrations:
        return
    await backend.ensure_history_table()
    applied = await backend.fetch_applied_names()
    for name, sql in migrations.items():
        if name in applied:
            continue
        try:
            await backend.execute_migration_body(sql)
        except Exception as error:
            logger.error(  # noqa: TRY400
                "migration failed",
                migration_name=name,
                error_type=type(error).__name__,
            )
            msg = f"migration {name!r} failed"
            raise MigrationError(msg) from error
        await backend.record_applied(name)
        logger.debug("migration applied", migration_name=name)
