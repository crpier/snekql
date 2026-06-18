"""Backend Runtime Adapter selection seam tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

from snektest import assert_eq, assert_raises, test

from snekql import mariadb, sqlite
from snekql._runtime_selection import resolve_runtime_config
from snekql.sqlite import DatabaseRuntimeError


@test(mark="fast")
def runtime_config_resolution_returns_backend_configs() -> None:
    """Backend config resolution yields configs that know their backend family."""

    legacy_config = resolve_runtime_config(
        backend=None,
        database=Path("app.db"),
        pool_size=2,
        acquire_timeout=0.5,
    )
    sqlite_config = sqlite.Config(database=Path("explicit.db"), pool_size=3)
    resolved_sqlite_config = resolve_runtime_config(
        backend=sqlite_config,
        database=None,
        pool_size=5,
        acquire_timeout=30.0,
    )
    mariadb_config = mariadb.Config(database="app", user="snekql")
    resolved_mariadb_config = resolve_runtime_config(
        backend=mariadb_config,
        database=None,
        pool_size=5,
        acquire_timeout=30.0,
    )

    assert_eq(legacy_config.backend_family, "sqlite")
    assert_eq(cast("sqlite.Config", legacy_config).database, Path("app.db"))
    assert_eq(cast("sqlite.Config", legacy_config).pool_size, 2)
    assert_eq(cast("sqlite.Config", legacy_config).acquire_timeout, 0.5)
    assert_eq(resolved_sqlite_config.backend_family, "sqlite")
    assert_eq(resolved_sqlite_config, sqlite_config)
    assert_eq(resolved_mariadb_config.backend_family, "mariadb")
    assert_eq(resolved_mariadb_config, mariadb_config)


@test(mark="fast")
def runtime_config_resolution_rejects_unsupported_or_ambiguous_input() -> None:
    """Unsupported backend selections fail before runtime modules initialize."""

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_config(
            backend=object(),
            database=None,
            pool_size=5,
            acquire_timeout=30.0,
        )

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_config(
            backend=sqlite.Config(database=":memory:"),
            database=Path("app.db"),
            pool_size=5,
            acquire_timeout=30.0,
        )

    with assert_raises(DatabaseRuntimeError):
        _ = resolve_runtime_config(
            backend=None,
            database=None,
            pool_size=5,
            acquire_timeout=30.0,
        )


@test(mark="fast")
def runtime_config_resolution_does_not_import_backend_runtime_modules() -> None:
    """Resolving a backend config avoids optional runtime imports."""

    script = """
from pathlib import Path
import sys
from snekql import mariadb, sqlite
from snekql._runtime_selection import resolve_runtime_config

_ = resolve_runtime_config(backend=None, database=Path('app.db'), pool_size=5, acquire_timeout=30.0)
_ = resolve_runtime_config(backend=sqlite.Config(database=':memory:'), database=None, pool_size=5, acquire_timeout=30.0)
_ = resolve_runtime_config(backend=mariadb.Config(database='app', user='snekql'), database=None, pool_size=5, acquire_timeout=30.0)
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
