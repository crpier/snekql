"""Backend Runtime Adapter selection seam tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import DatabaseRuntimeError, mariadb, sqlite
from snekql._runtime_selection import resolve_runtime_selection


@test(mark="fast")
def runtime_selection_resolves_backend_family_and_config() -> None:
    """Backend config resolution lives in one Runtime Adapter selection seam."""

    legacy_selection = resolve_runtime_selection(
        backend=None,
        database=Path("app.db"),
        pool_size=2,
        acquire_timeout=0.5,
    )
    sqlite_config = sqlite.Config(database=Path("explicit.db"), pool_size=3)
    sqlite_selection = resolve_runtime_selection(
        backend=sqlite_config,
        database=None,
        pool_size=5,
        acquire_timeout=30.0,
    )
    mariadb_config = mariadb.Config(database="app", user="snekql")
    mariadb_selection = resolve_runtime_selection(
        backend=mariadb_config,
        database=None,
        pool_size=5,
        acquire_timeout=30.0,
    )

    assert_eq(legacy_selection.backend_family, "sqlite")
    assert_eq(cast("sqlite.Config", legacy_selection.config).database, Path("app.db"))
    assert_eq(cast("sqlite.Config", legacy_selection.config).pool_size, 2)
    assert_eq(cast("sqlite.Config", legacy_selection.config).acquire_timeout, 0.5)
    assert_eq(sqlite_selection.backend_family, "sqlite")
    assert_eq(sqlite_selection.config, sqlite_config)
    assert_eq(mariadb_selection.backend_family, "mariadb")
    assert_eq(mariadb_selection.config, mariadb_config)


@test(mark="fast")
def runtime_selection_rejects_unsupported_or_ambiguous_configuration() -> None:
    """Unsupported backend selections fail before runtime modules initialize."""

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_selection(
            backend=object(),
            database=None,
            pool_size=5,
            acquire_timeout=30.0,
        )

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_selection(
            backend=sqlite.Config(database=":memory:"),
            database=Path("app.db"),
            pool_size=5,
            acquire_timeout=30.0,
        )

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_selection(
            backend=None,
            database=None,
            pool_size=5,
            acquire_timeout=30.0,
        )


@test(mark="fast")
def runtime_selection_does_not_import_backend_runtime_modules() -> None:
    """Resolving a backend adapter selection avoids optional runtime imports."""

    script = """
from pathlib import Path
import sys
from snekql import mariadb, sqlite
from snekql._runtime_selection import resolve_runtime_selection

_ = resolve_runtime_selection(backend=None, database=Path('app.db'), pool_size=5, acquire_timeout=30.0)
_ = resolve_runtime_selection(backend=sqlite.Config(database=':memory:'), database=None, pool_size=5, acquire_timeout=30.0)
_ = resolve_runtime_selection(backend=mariadb.Config(database='app', user='snekql'), database=None, pool_size=5, acquire_timeout=30.0)
for name in ('snekql.sqlite.runtime', 'snekql.mariadb.runtime', 'aiosqlite', 'aiomysql'):
    if name in sys.modules:
        raise AssertionError(f'{name} was imported')
print('ok')
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_eq(result.stdout.strip(), "ok")
