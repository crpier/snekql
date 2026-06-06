"""Temporary MariaDB Test Server public API tests."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import (
    assert_eq,
    assert_in,
    assert_is_none,
    assert_raises,
    assert_true,
    test,
)

from snekql import mariadb
from snekql.testing.mariadb import (
    TemporaryMariaDBServer,
    TemporaryMariaDBServerError,
    temporary_mariadb_server,
)


@test(mark="fast")
def temporary_mariadb_server_rejects_invalid_option_combinations() -> None:
    """Invalid test-server option combinations fail before startup."""

    invalid_calls = (
        (
            lambda: temporary_mariadb_server(transports=set()),
            "at least one transport",
        ),
        (
            lambda: temporary_mariadb_server(clean_before_start=True),
            "clean_before_start requires data_directory",
        ),
        (
            lambda: temporary_mariadb_server(port=3307),
            "port requires tcp transport",
        ),
        (
            lambda: temporary_mariadb_server(
                transports={"tcp"},
                socket_path=Path("mariadb.sock"),
            ),
            "socket_path requires unix_socket transport",
        ),
        (
            lambda: temporary_mariadb_server(auth="insecure", password="test"),
            "password requires auth='password'",
        ),
        (
            lambda: temporary_mariadb_server(database="test-db"),
            "MariaDB database must be",
        ),
        (
            lambda: temporary_mariadb_server(user="test-user"),
            "MariaDB user must be",
        ),
        (
            lambda: temporary_mariadb_server(server_args=("--port=3307",)),
            "managed mariadbd option",
        ),
        (
            lambda: temporary_mariadb_server(
                clean_before_start=True,
                data_directory=Path("data"),
                reset_database=True,
            ),
            "reset_database is incompatible with clean_before_start",
        ),
    )

    for invalid_call, expected_message in invalid_calls:
        with assert_raises(TemporaryMariaDBServerError) as error:
            _ = invalid_call()
        assert_in(expected_message, str(error.exception))


@test(mark="fast")
def temporary_mariadb_server_config_prefers_unix_socket() -> None:
    """Server configs expose requested transports and prefer Unix socket."""

    server = TemporaryMariaDBServer(
        auth="password",
        database="test",
        data_directory=Path("data"),
        error_log_path=Path("mariadb.err"),
        host="127.0.0.1",
        password="secret",
        pid_path=Path("mariadb.pid"),
        port=4306,
        socket_path=Path("mariadb.sock"),
        transports=frozenset({"unix_socket", "tcp"}),
        user="root",
    )

    default_config = server.config(pool_size=2, acquire_timeout=3.0)
    assert_eq(
        default_config,
        mariadb.Config(
            database="test",
            user="root",
            password="secret",
            unix_socket=Path("mariadb.sock"),
            pool_size=2,
            acquire_timeout=3.0,
        ),
    )

    tcp_config = server.config(transport="tcp")
    assert_eq(tcp_config.host, "127.0.0.1")
    assert_eq(tcp_config.port, 4306)
    assert_is_none(tcp_config.unix_socket)

    with assert_raises(TemporaryMariaDBServerError):
        _ = TemporaryMariaDBServer(
            auth="insecure",
            database="test",
            data_directory=Path("data"),
            error_log_path=Path("mariadb.err"),
            host=None,
            password="",
            pid_path=Path("mariadb.pid"),
            port=None,
            socket_path=Path("mariadb.sock"),
            transports=frozenset({"unix_socket"}),
            user="root",
        ).config(transport="tcp")


@test(mark="fast")
async def temporary_mariadb_server_resolves_relative_data_directories() -> None:
    """Relative data directories are made absolute before invoking MariaDB."""

    with TemporaryDirectory() as temporary_directory:
        base_directory = Path(temporary_directory)
        install_db = base_directory / "mariadb-install-db"
        _ = install_db.write_text(
            "".join(
                (
                    "#!/bin/sh\n",
                    "printf '%s\\n' \"$@\" >&2\n",
                    "exit 1\n",
                )
            ),
        )
        _ = install_db.chmod(0o700)
        relative_data_directory = Path("relative-mariadb-data")
        expected_data_directory = Path.cwd() / relative_data_directory

        with assert_raises(TemporaryMariaDBServerError) as error:
            async with temporary_mariadb_server(
                data_directory=relative_data_directory,
                install_db=install_db,
            ):
                pass

    assert_in(f"--datadir={expected_data_directory}", str(error.exception))


@test(mark="fast")
async def temporary_mariadb_server_explains_quota_limited_install_failures() -> None:
    """Install failures caused by quota exhaustion include cleanup guidance."""

    with TemporaryDirectory() as temporary_directory:
        install_db = Path(temporary_directory) / "mariadb-install-db"
        _ = install_db.write_text(
            "".join(
                (
                    "#!/bin/sh\n",
                    "echo 'InnoDB: preallocating 100663296 bytes failed with error 122' >&2\n",
                    "exit 1\n",
                )
            ),
        )
        _ = install_db.chmod(0o700)

        with assert_raises(TemporaryMariaDBServerError) as error:
            async with temporary_mariadb_server(install_db=install_db):
                pass

    message = str(error.exception)
    assert_in("quota-limited filesystem", message)
    assert_in("clean retained temporary MariaDB data directories", message)
    assert_in("data_directory", message)


@test(mark="medium")
async def temporary_mariadb_server_starts_with_default_unix_socket() -> None:
    """The public helper starts a queryable Unix-socket server by default."""

    data_directory: Path | None = None
    try:
        async with temporary_mariadb_server() as server:
            result = await server.run_sql("SELECT 1")
            config = server.config()
            data_directory = server.data_directory

            assert_eq(server.transports, frozenset({"unix_socket"}))
            assert_is_none(server.host)
            assert_is_none(server.port)
            assert_eq(config.unix_socket, server.socket_path)
            assert_in("1", result.stdout)

        assert_true(data_directory.exists())
    finally:
        if data_directory is not None:
            await asyncio.to_thread(shutil.rmtree, data_directory, ignore_errors=True)


@test(mark="medium")
async def temporary_mariadb_server_reset_database_drops_reused_tables() -> None:
    """The public reset helper removes stale tables from a reused database."""

    with TemporaryDirectory() as temporary_directory:
        data_directory = Path(temporary_directory) / "data"
        async with temporary_mariadb_server(data_directory=data_directory) as server:
            _ = await server.run_sql("CREATE TABLE stale_public_table (`id` INT)")

        async with temporary_mariadb_server(data_directory=data_directory) as server:
            await server.reset_database()
            result = await server.run_sql("SHOW TABLES LIKE 'stale_public_table'")

    assert_eq(result.stdout, "")


@test(mark="medium")
async def temporary_mariadb_server_reset_database_option_runs_before_yield() -> None:
    """The startup option resets reused data directories before yielding."""

    with TemporaryDirectory() as temporary_directory:
        data_directory = Path(temporary_directory) / "data"
        async with temporary_mariadb_server(data_directory=data_directory) as server:
            _ = await server.run_sql("CREATE TABLE stale_option_table (`id` INT)")

        async with temporary_mariadb_server(
            data_directory=data_directory,
            reset_database=True,
        ) as server:
            result = await server.run_sql("SHOW TABLES LIKE 'stale_option_table'")

    assert_eq(result.stdout, "")


@test(mark="medium")
async def temporary_mariadb_server_supports_password_auth() -> None:
    """Password-auth test servers generate usable credentials."""

    with TemporaryDirectory() as temporary_directory:
        data_directory = Path(temporary_directory) / "data"
        async with temporary_mariadb_server(
            auth="password",
            data_directory=data_directory,
        ) as server:
            result = await server.run_sql("SELECT 1")

            assert_eq(server.auth, "password")
            assert server.password != ""
            assert_in("1", result.stdout)
