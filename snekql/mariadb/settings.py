"""Required per-connection MariaDB settings and a minimum-version guard.

aiomysql has no per-connection init hook, so these are applied the first time
the pool hands out each physical connection. The session settings give MariaDB
the same correctness posture snekql relies on for SQLite:

* ``sql_mode`` with ``STRICT_ALL_TABLES`` is the runtime analogue of SQLite
  ``STRICT`` tables, and ``NO_ENGINE_SUBSTITUTION`` turns a missing InnoDB into
  an error instead of a silent storage-engine swap that would drop foreign keys.
* ``foreign_key_checks`` keeps the emitted ``FOREIGN KEY`` constraints enforced.
* ``time_zone`` pins the session to UTC so server-side ``CURRENT_TIMESTAMP``
  defaults match snekql's UTC datetime codec.

The version guard fails fast on servers older than the supported minimum (or on
non-MariaDB servers such as MySQL) rather than letting feature gaps surface as
obscure runtime errors later.
"""

from __future__ import annotations

from typing import Any, cast

from snekql._settings import (
    ConnectionSetting,
    SettingsProbe,
    apply_connection_settings,
)
from snekql.errors import DatabaseRuntimeError

# Lowest MariaDB version snekql is validated against. Lower this once wider
# version coverage is tested; raising it is a breaking change.
MARIADB_MINIMUM_VERSION: tuple[int, ...] = (12, 2)

# sql_mode flags snekql depends on; the full mode is set, then these are
# verified as a subset so server-added flags do not trip the check.
_REQUIRED_SQL_MODE_FLAGS: frozenset[str] = frozenset(
    {"STRICT_ALL_TABLES", "NO_ENGINE_SUBSTITUTION"}
)
_DESIRED_SQL_MODE = (
    "STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_ZERO_DATE,"
    "NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO"
)


def _sql_mode_has_required_flags(value: object) -> bool:
    if not isinstance(value, str):
        return False
    flags = {flag.strip() for flag in value.split(",") if flag.strip()}
    return flags >= _REQUIRED_SQL_MODE_FLAGS


MARIADB_SESSION_SETTINGS: tuple[ConnectionSetting, ...] = (
    ConnectionSetting(
        name="sql_mode",
        apply_statements=(f"SET SESSION sql_mode = '{_DESIRED_SQL_MODE}'",),
        probe_sql="SELECT @@SESSION.sql_mode",
        predicate=_sql_mode_has_required_flags,
        expectation="STRICT_ALL_TABLES and NO_ENGINE_SUBSTITUTION enabled",
    ),
    ConnectionSetting(
        name="time_zone",
        apply_statements=("SET time_zone = '+00:00'",),
        probe_sql="SELECT @@SESSION.time_zone",
        expected_value="+00:00",
        expectation="'+00:00' (UTC)",
    ),
    ConnectionSetting(
        name="foreign_key_checks",
        apply_statements=("SET SESSION foreign_key_checks = 1",),
        probe_sql="SELECT @@SESSION.foreign_key_checks",
        expected_value=1,
        expectation="1 (ON)",
    ),
)


def _parse_mariadb_version(value: object) -> tuple[int, ...] | None:
    """Parse the leading numeric version from a MariaDB ``VERSION()`` string."""

    if not isinstance(value, str) or "mariadb" not in value.lower():
        return None
    head = value.split("-", 1)[0]
    parts: list[int] = []
    for part in head.split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts) if parts else None


def _format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


class _MariaDBSettingsProbe:
    """Apply/verify probe backed by an aiomysql connection."""

    def __init__(self, connection: object) -> None:
        self.connection: object = connection

    async def execute(self, sql: str) -> None:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(sql)
        finally:
            await _close_cursor(cursor)

    async def fetch_value(self, sql: str) -> object:
        cursor = await cast("Any", self.connection).cursor()
        try:
            _ = await cursor.execute(sql)
            row = await cursor.fetchone()
        finally:
            await _close_cursor(cursor)
        if row is None:
            return None
        return row[0]


async def _close_cursor(cursor: object) -> None:
    close_result = cast("Any", cursor).close()
    if close_result is not None:
        _ = await close_result


async def verify_mariadb_version(probe: SettingsProbe) -> None:
    """Reject servers that are not MariaDB or are below the supported minimum."""

    raw_version = await probe.fetch_value("SELECT VERSION()")
    parsed = _parse_mariadb_version(raw_version)
    if parsed is None:
        msg = (
            "snekql requires MariaDB "
            f">= {_format_version(MARIADB_MINIMUM_VERSION)}; connected server "
            f"reported {raw_version!r}"
        )
        raise DatabaseRuntimeError(msg)
    if parsed < MARIADB_MINIMUM_VERSION:
        msg = (
            "snekql requires MariaDB "
            f">= {_format_version(MARIADB_MINIMUM_VERSION)}; connected server "
            f"is {_format_version(parsed)}"
        )
        raise DatabaseRuntimeError(msg)


async def configure_mariadb_connection(connection: object) -> None:
    """Verify version then apply/verify required session settings on one connection."""

    probe = _MariaDBSettingsProbe(connection)
    await verify_mariadb_version(probe)
    await apply_connection_settings(
        probe,
        MARIADB_SESSION_SETTINGS,
        backend="mariadb",
    )


__all__ = [
    "MARIADB_MINIMUM_VERSION",
    "MARIADB_SESSION_SETTINGS",
    "configure_mariadb_connection",
    "verify_mariadb_version",
]
