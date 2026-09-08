"""Temporary server credentials survive SQL string-literal parsing."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from signal import SIGINT
from tempfile import TemporaryDirectory

from snektest import Param, assert_eq, test

from snekql import mariadb
from snekql.testing.mariadb import temporary_mariadb_server


@test(
    [
        Param(value=mode, name=mode or "ordinary")
        for mode in ("", "NO_BACKSLASH_ESCAPES")
    ],
    [Param(value=user, name=user) for user in ("root", "worker")],
    [
        Param(value=password, name=name)
        for name, password in (
            ("backslash", r"harmless\path_345"),
            ("quote", "harmless'quote_345"),
            ("mixed", "harmless\\'quoted\\\\tail\\"),
        )
    ],
    mark="slow",
)
async def password_authenticates(mode: str, user: str, password: str) -> None:
    """The caller's exact password works with ordinary backslash SQL escaping."""
    with TemporaryDirectory() as directory:
        async with temporary_mariadb_server(
            auth="password",
            password=password,
            user=user,
            data_directory=Path(directory) / "data",
            server_args=(f"--sql-mode={mode}",),
        ) as server:
            result = await server.run_sql("SELECT 1")
            session_mode = await server.run_sql(
                "SELECT CONCAT('mode:', @@SESSION.sql_mode)"
            )
            assert_eq(session_mode.stdout.strip().split("\n")[-1], f"mode:{mode}")
    assert_eq(result.returncode, 0)


@test(
    [
        Param(value=mode, name=mode or "ordinary")
        for mode in ("", "NO_BACKSLASH_ESCAPES")
    ],
    [Param(value=user, name=user) for user in ("root", "worker")],
    mark="slow",
)
async def cli_environment_password_authenticates(mode: str, user: str) -> None:
    """The foreground CLI preserves the exact password supplied via environment."""
    password = "harmless\\'env\\tail_345"
    with TemporaryDirectory() as directory:
        socket_path = Path(directory) / "db.sock"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-m",
            "snekql.testing.mariadb.cli",
            "--auth",
            "password",
            "--password-env",
            "SNEKQL_TEST_PASSWORD",
            "--user",
            user,
            "--data-directory",
            str(Path(directory) / "data"),
            "--socket-path",
            str(socket_path),
            f"--server-arg=--sql-mode={mode}",
            env={**os.environ, "SNEKQL_TEST_PASSWORD": password},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert process.stderr is not None
            async with asyncio.timeout(60):
                while True:
                    line = await process.stderr.readline()
                    if b"Press Ctrl-C to stop." in line:
                        break
                    assert line, "CLI exited before readiness"
            async with (
                await mariadb.Database.initialize(
                    mariadb.Config(
                        unix_socket=socket_path,
                        user=user,
                        password=password,
                        database="test",
                    )
                ) as database,
                database.transaction(),
            ):
                pass
        finally:
            if process.returncode is None:
                process.send_signal(SIGINT)
            try:
                await asyncio.wait_for(process.communicate(), 25)
            except TimeoutError:
                process.kill()
                await process.communicate()
                raise
        assert_eq(process.returncode, 130)
