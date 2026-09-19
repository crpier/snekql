"""Required per-connection SQLite settings, applied and verified at open.

Every physical connection applies and verifies its configured policy before
entering the pool. File-backed databases use WAL with NORMAL synchronization by
default, or FULL synchronization when requested. In-memory databases retain
SQLite's native journal/synchronization behavior and have no crash durability.
Foreign-key enforcement, busy waiting, and UTF-8 verification apply to both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from snekql._settings import ConnectionSetting, apply_connection_settings

if TYPE_CHECKING:
    from aiosqlite import Connection

# Milliseconds a busy connection waits for a lock before failing. Chosen so a
# pool of writers serializes instead of surfacing transient lock contention.
SQLITE_BUSY_TIMEOUT_MS = 5000

_SQLITE_WAL_SETTING = ConnectionSetting(
    name="journal_mode",
    apply_statements=("PRAGMA journal_mode = WAL",),
    probe_sql="PRAGMA journal_mode",
    expected_value="wal",
    expectation="'wal'",
)
"""Both supported file-backed durability policies require WAL."""

SQLITE_FILE_CONNECTION_SETTINGS: tuple[ConnectionSetting, ...] = (
    _SQLITE_WAL_SETTING,
    ConnectionSetting(
        name="synchronous",
        apply_statements=("PRAGMA synchronous = NORMAL",),
        probe_sql="PRAGMA synchronous",
        expected_value=1,
        expectation="1 (NORMAL)",
    ),
)

SQLITE_CONNECTION_SETTINGS: tuple[ConnectionSetting, ...] = (
    ConnectionSetting(
        name="foreign_keys",
        apply_statements=("PRAGMA foreign_keys = ON",),
        probe_sql="PRAGMA foreign_keys",
        expected_value=1,
        expectation="1 (ON)",
    ),
    ConnectionSetting(
        name="busy_timeout",
        apply_statements=(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}",),
        probe_sql="PRAGMA busy_timeout",
        expected_value=SQLITE_BUSY_TIMEOUT_MS,
        expectation=str(SQLITE_BUSY_TIMEOUT_MS),
    ),
    ConnectionSetting(
        name="encoding",
        probe_sql="PRAGMA encoding",
        expected_value="UTF-8",
        expectation="'UTF-8'",
    ),
)


class _SQLiteSettingsProbe:
    """Apply/verify probe backed by an aiosqlite connection."""

    def __init__(self, connection: Connection) -> None:
        self.connection: Connection = connection

    async def execute(self, sql: str) -> None:
        cursor = await self.connection.execute(sql)
        await cursor.close()

    async def fetch_value(self, sql: str) -> object:
        cursor = await self.connection.execute(sql)
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return row[0] if row is not None else None


async def apply_sqlite_connection_settings(
    connection: Connection,
    *,
    file_backed: bool,
    durability: Literal["normal", "full"] = "normal",
) -> None:
    """Apply and verify the required PRAGMAs on one SQLite connection."""

    file_settings = SQLITE_FILE_CONNECTION_SETTINGS
    if durability == "full":
        file_settings = (
            _SQLITE_WAL_SETTING,
            ConnectionSetting(
                name="synchronous",
                apply_statements=("PRAGMA synchronous = FULL",),
                probe_sql="PRAGMA synchronous",
                expected_value=2,
                expectation="2 (FULL)",
            ),
        )
    await apply_connection_settings(
        _SQLiteSettingsProbe(connection),
        (
            file_settings + SQLITE_CONNECTION_SETTINGS
            if file_backed
            else SQLITE_CONNECTION_SETTINGS
        ),
        backend="sqlite",
    )


__all__ = [
    "SQLITE_BUSY_TIMEOUT_MS",
    "SQLITE_CONNECTION_SETTINGS",
    "SQLITE_FILE_CONNECTION_SETTINGS",
    "apply_sqlite_connection_settings",
]
