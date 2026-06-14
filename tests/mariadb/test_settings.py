"""Unit tests for MariaDB version guard and session-setting predicates."""

from __future__ import annotations

from snektest import assert_raises, assert_true, test

from snekql._settings import apply_connection_settings
from snekql.errors import DatabaseRuntimeError
from snekql.mariadb.settings import (
    MARIADB_SESSION_SETTINGS,
    verify_mariadb_version,
)


class _FakeProbe:
    """Probe returning canned values keyed by probe SQL."""

    def __init__(self, values: dict[str, object]) -> None:
        self.values: dict[str, object] = values
        self.executed: list[str] = []

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)

    async def fetch_value(self, sql: str) -> object:
        return self.values[sql]


@test(mark="fast")
async def version_guard_accepts_supported_mariadb() -> None:
    """A modern MariaDB build at or above the minimum passes the guard."""

    probe = _FakeProbe({"SELECT VERSION()": "12.2.2-MariaDB-log"})

    await verify_mariadb_version(probe)


@test(mark="fast")
async def version_guard_rejects_old_mariadb() -> None:
    """A MariaDB build below the supported minimum fails fast."""

    probe = _FakeProbe({"SELECT VERSION()": "10.5.21-MariaDB"})

    with assert_raises(DatabaseRuntimeError) as caught:
        await verify_mariadb_version(probe)

    assert_true("MariaDB" in str(caught.exception))


@test(mark="fast")
async def version_guard_rejects_non_mariadb_servers() -> None:
    """A non-MariaDB server (for example MySQL) is rejected."""

    probe = _FakeProbe({"SELECT VERSION()": "8.0.36"})

    with assert_raises(DatabaseRuntimeError):
        await verify_mariadb_version(probe)


@test(mark="fast")
async def session_settings_reject_a_non_strict_sql_mode() -> None:
    """A server that drops STRICT_ALL_TABLES from sql_mode fails verification."""

    probe = _FakeProbe(
        {
            "SELECT @@SESSION.sql_mode": "NO_ZERO_DATE",
            "SELECT @@SESSION.time_zone": "+00:00",
            "SELECT @@SESSION.foreign_key_checks": 1,
        }
    )

    with assert_raises(DatabaseRuntimeError) as caught:
        await apply_connection_settings(
            probe, MARIADB_SESSION_SETTINGS, backend="mariadb"
        )

    assert_true("sql_mode" in str(caught.exception))


@test(mark="fast")
async def session_settings_accept_strict_sql_mode_with_extra_flags() -> None:
    """Extra server-added sql_mode flags do not trip the subset check."""

    probe = _FakeProbe(
        {
            "SELECT @@SESSION.sql_mode": (
                "STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_AUTO_CREATE_USER"
            ),
            "SELECT @@SESSION.time_zone": "+00:00",
            "SELECT @@SESSION.foreign_key_checks": 1,
        }
    )

    await apply_connection_settings(probe, MARIADB_SESSION_SETTINGS, backend="mariadb")
