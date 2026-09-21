"""Unit tests for MariaDB version guard and session-setting predicates."""

from __future__ import annotations

from snektest import Param, assert_raises, assert_true, test

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


@test(
    [
        Param("10.11.2-MariaDB-ubu2204", name="lts-10.11"),
        Param("11.4.2-MariaDB-log", name="lts-11.4"),
        Param("11.8.2-MariaDB", name="lts-11.8"),
        Param("12.3.3-MariaDB-ubu2404", name="lts-12.3"),
        Param("12.2.2-MariaDB-log", name="compatibility-12.2"),
    ],
    mark="fast",
)
async def version_guard_accepts_supported_mariadb(version: str) -> None:
    """Maintained LTS families and the previous minimum pass admission."""

    probe = _FakeProbe({"SELECT VERSION()": version})

    await verify_mariadb_version(probe)


@test(
    [
        Param("10.5.21-MariaDB", name="old-lts"),
        Param("10.6.99-MariaDB", name="retired-lts"),
        Param("10.10.99-MariaDB", name="below-floor"),
    ],
    mark="fast",
)
async def version_guard_rejects_old_mariadb(version: str) -> None:
    """Older families fail with the new admission floor in the diagnostic."""

    probe = _FakeProbe({"SELECT VERSION()": version})

    with assert_raises(DatabaseRuntimeError) as caught:
        await verify_mariadb_version(probe)

    assert_true("MariaDB >= 10.11" in str(caught.exception))


@test(
    [
        Param("8.0.36", name="mysql"),
        Param("12.3.3", name="unidentified-newer-server"),
        Param("unknown-MariaDB", name="malformed"),
        Param(None, name="missing"),
    ],
    mark="fast",
)
async def version_guard_rejects_non_mariadb_servers(version: object) -> None:
    """A newer number alone cannot establish the required backend identity."""

    probe = _FakeProbe({"SELECT VERSION()": version})

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
            "SELECT @@SESSION.check_constraint_checks": 1,
            "SELECT @@SESSION.unique_checks": 1,
            "SELECT @@innodb_page_size": 16384,
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
            "SELECT @@SESSION.check_constraint_checks": 1,
            "SELECT @@SESSION.unique_checks": 1,
            "SELECT @@innodb_page_size": 16384,
        }
    )

    await apply_connection_settings(probe, MARIADB_SESSION_SETTINGS, backend="mariadb")


@test(mark="fast")
async def session_settings_reject_small_innodb_pages() -> None:
    """History's full byte-exact name index requires at least 8 KiB pages."""

    probe = _FakeProbe(
        {
            "SELECT @@SESSION.sql_mode": ("STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION"),
            "SELECT @@SESSION.time_zone": "+00:00",
            "SELECT @@SESSION.foreign_key_checks": 1,
            "SELECT @@SESSION.check_constraint_checks": 1,
            "SELECT @@SESSION.unique_checks": 1,
            "SELECT @@innodb_page_size": 4096,
        }
    )

    with assert_raises(DatabaseRuntimeError) as caught:
        await apply_connection_settings(
            probe, MARIADB_SESSION_SETTINGS, backend="mariadb"
        )

    assert_true("innodb_page_size" in str(caught.exception))
