"""Temporary MariaDB Test Server CLI tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from signal import SIGINT
from tempfile import TemporaryDirectory

from snektest import Param, assert_eq, assert_in, test


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


@test(
    [
        Param(value=None, name="no-environment-password"),
        Param(value="SNEKQL_TEST_PASSWORD", name="empty-environment-password"),
    ],
    mark="slow",
)
async def generated_password_is_hidden_in_cli_output(password_env: str | None) -> None:
    """The real foreground CLI announces generated credentials without revealing them."""
    with TemporaryDirectory() as directory:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-m",
            "snekql.testing.mariadb.cli",
            "--auth",
            "password",
            "--runtime-base-directory",
            directory,
            "--data-directory",
            str(Path(directory) / "data"),
            "--socket-path",
            str(Path(directory) / "db.sock"),
            *(("--password-env", password_env) if password_env is not None else ()),
            env={**os.environ, "SNEKQL_TEST_PASSWORD": ""},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        startup_output = bytearray()
        try:
            assert process.stderr is not None
            async with asyncio.timeout(60):
                while True:
                    line = await process.stderr.readline()
                    startup_output.extend(line)
                    if b"Press Ctrl-C to stop." in line:
                        break
                    assert line, "CLI exited before readiness"
        finally:
            if process.returncode is None:
                process.send_signal(SIGINT)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), 25)
            except TimeoutError:
                process.kill()
                await process.communicate()
                raise
        assert_eq(process.returncode, 130)
        output = bytes(startup_output) + stderr
        password_lines = [
            line for line in output.splitlines() if line.startswith(b"password:")
        ]
        assert_eq(password_lines, [b"password: [generated; hidden]"])
        assert_in(b" -p ", stdout)
