"""Temporary MariaDB Test Server CLI tests."""

from __future__ import annotations

import subprocess
import sys

from snektest import assert_eq, assert_in, test


@test(mark="fast")
def mariadb_server_cli_documents_foreground_options() -> None:
    """The foreground CLI exposes the public test-server options."""

    result = subprocess.run(
        [sys.executable, "-m", "snekql.testing.mariadb.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert_eq(result.returncode, 0)
    assert_in("snekql-mariadb-server", result.stdout)
    assert_in("--transport", result.stdout)
    assert_in("--password-env", result.stdout)
    assert_in("--server-arg", result.stdout)
    assert_in("--socket-path", result.stdout)
    assert_in("--reset-database", result.stdout)
