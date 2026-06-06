"""Temporary MariaDB Test Server public API tests."""

from __future__ import annotations

from pathlib import Path

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


@test(mark="medium")
async def temporary_mariadb_server_starts_with_default_unix_socket() -> None:
    """The public helper starts a queryable Unix-socket server by default."""

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


@test(mark="medium")
async def temporary_mariadb_server_supports_password_auth() -> None:
    """Password-auth test servers generate usable credentials."""

    async with temporary_mariadb_server(auth="password") as server:
        result = await server.run_sql("SELECT 1")

        assert_eq(server.auth, "password")
        assert server.password != ""
        assert_in("1", result.stdout)
