"""Local aiosqlite compatibility adapter for worker-owned buffered cleanup.

Private dependency: aiosqlite's ``_execute_fetchall`` worker callback and ``_conn``
property (0.22.1). Keep this dependency here and exercise native cleanup failures
and interrupted worker lifetimes when updating the driver. Do not patch aiosqlite
classes globally: all other driver methods retain their original implementation.
"""

lazy import sqlite3
lazy from typing import Any

lazy import aiosqlite
lazy from aiosqlite import Connection


class BufferedExecuteConstraintError(Exception):
    """Preserve execution-stage evidence separately from fetch/cleanup failures."""

    def __init__(self, original: sqlite3.IntegrityError) -> None:
        super().__init__()
        self.original = original


class BufferedConnection(Connection):
    """Complete native cursor cleanup inside the combined worker operation."""

    def _execute_fetchall(self, sql: str, parameters: Any) -> list[Any]:
        try:
            cursor = self._conn.execute(sql, parameters)
        except sqlite3.IntegrityError as error:
            raise BufferedExecuteConstraintError(error) from error
        try:
            return cursor.fetchall()
        finally:
            cursor.close()


def connect(database: str) -> Connection:
    """Use the driver's worker/start/close lifecycle with our local subclass."""
    # Future releases must not silently bypass our worker cleanup callback.
    # Keep their supported cursor lifecycle until compatibility is reviewed.
    if aiosqlite.__version__ != "0.22.1":
        return aiosqlite.connect(database, isolation_level=None)
    return BufferedConnection(
        lambda: sqlite3.connect(database, isolation_level=None),
        iter_chunk_size=64,
    )
