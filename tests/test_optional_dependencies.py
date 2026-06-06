"""Optional backend dependency contract tests."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import metadata

from snektest import assert_eq, assert_in, test


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    """Run an import-isolated Python snippet in the current test environment."""

    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


@test()
def package_metadata_declares_backend_driver_extras() -> None:
    """SQLite and MariaDB drivers are optional backend extras."""

    package_metadata = metadata("snekql")
    extras = package_metadata.get_all("Provides-Extra") or []
    requirements = package_metadata.get_all("Requires-Dist") or []

    assert_in("aiosqlite", extras)
    assert_in("aiomysql", extras)
    assert any(
        requirement.startswith("aiosqlite") and "extra == 'aiosqlite'" in requirement
        for requirement in requirements
    )
    assert any(
        requirement.startswith("aiomysql") and "extra == 'aiomysql'" in requirement
        for requirement in requirements
    )
    assert not any(
        requirement.startswith(("aiosqlite", "aiomysql"))
        and "extra ==" not in requirement
        for requirement in requirements
    )


@test()
def public_imports_do_not_import_optional_drivers() -> None:
    """Root and backend namespace imports do not load optional database drivers."""

    script = """
import sys
import snekql
from tests.logging_helpers import NULL_LOGGER
from snekql import mariadb, sqlite
from snekql.testing import mariadb as testing_mariadb

if "aiosqlite" in sys.modules:
    raise AssertionError("aiosqlite was imported")
if "aiomysql" in sys.modules:
    raise AssertionError("aiomysql was imported")
if "snekql._pool" in sys.modules:
    raise AssertionError("SQLite pool was imported")
if "snekql.schema" in sys.modules:
    raise AssertionError("SQLite schema was imported")
_ = sqlite.Config(database=":memory:")
_ = mariadb.Config(database="app", user="snekql")
_ = testing_mariadb.temporary_mariadb_server()
print("ok")
"""

    result = _run_python(script)

    assert_eq(result.returncode, 0)
    assert_eq(result.stdout.strip(), "ok")


@test(mark="medium")
def sqlite_initialization_without_extra_reports_install_hint() -> None:
    """Runtime initialization explains how to install a missing SQLite driver."""

    script = """
from __future__ import annotations

import asyncio
import builtins

import snekql
from snekql import Database, sqlite
from tests.logging_helpers import NULL_LOGGER

original_import = builtins.__import__


def block_aiosqlite(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "aiosqlite" or name.startswith("aiosqlite."):
        raise ModuleNotFoundError("No module named 'aiosqlite'", name="aiosqlite")
    return original_import(name, globals, locals, fromlist, level)


async def main() -> None:
    builtins.__import__ = block_aiosqlite
    try:
        try:
            _ = await Database.initialize(NULL_LOGGER, sqlite.Config(database=":memory:"))
        except snekql.DatabaseRuntimeError as error:
            print(error)
            return
        raise AssertionError("SQLite initialization unexpectedly succeeded")
    finally:
        builtins.__import__ = original_import


asyncio.run(main())
"""

    result = _run_python(script)

    assert_eq(result.returncode, 0)
    assert_in("snekql[aiosqlite]", result.stdout)
