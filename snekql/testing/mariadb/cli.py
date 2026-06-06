"""Foreground CLI for the Temporary MariaDB Test Server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from snekql.testing.mariadb import (
    MariaDBAuth,
    MariaDBTransport,
    TemporaryMariaDBServer,
    TemporaryMariaDBServerError,
    temporary_mariadb_server,
)
from snekql.testing.mariadb._commands import MariaDBClientCommand


@dataclass(frozen=True, kw_only=True)
class _CLIOptions:
    """Parsed foreground CLI options."""

    auth: MariaDBAuth
    clean_before_start: bool
    client: str | Path
    data_directory: Path | None
    database: str
    install_db: str | Path
    mariadbd: str | Path
    password: str | None
    port: int | None
    reset_database: bool
    server_args: tuple[str, ...]
    socket_path: Path | None
    startup_timeout: float
    transports: set[MariaDBTransport] | None
    user: str


def _build_parser() -> argparse.ArgumentParser:
    """Define the foreground CLI surface around the public API."""

    parser = argparse.ArgumentParser(
        prog="snekql-mariadb-server",
        description="Start a foreground Temporary MariaDB Test Server.",
    )
    _ = parser.add_argument(
        "--auth",
        choices=("insecure", "password"),
        default="insecure",
        help="authentication policy; default: insecure",
    )
    _ = parser.add_argument(
        "--transport",
        action="append",
        choices=("unix_socket", "tcp"),
        dest="transports",
        help="connection transport to expose; repeat for both; default: unix_socket",
    )
    _ = parser.add_argument("--data-directory", type=Path)
    _ = parser.add_argument("--clean-before-start", action="store_true")
    _ = parser.add_argument("--reset-database", action="store_true")
    _ = parser.add_argument("--database", default="test")
    _ = parser.add_argument("--user", default="root")
    _ = parser.add_argument("--password-env")
    _ = parser.add_argument("--port", type=int)
    _ = parser.add_argument("--socket-path", type=Path)
    _ = parser.add_argument(
        "--server-arg",
        action="append",
        default=[],
        help="extra mariadbd argument; repeat as needed; use --server-arg=VALUE",
    )
    _ = parser.add_argument("--mariadbd", default="mariadbd")
    _ = parser.add_argument("--install-db", default="mariadb-install-db")
    _ = parser.add_argument("--client", default="mariadb")
    _ = parser.add_argument("--startup-timeout", type=float, default=20.0)
    return parser


def _parse_options(argv: list[str] | None) -> _CLIOptions:
    """Parse and normalize argv before delegating to the public API."""

    parser = _build_parser()
    namespace = parser.parse_args(argv)
    auth = namespace.auth
    if auth not in {"insecure", "password"}:
        parser.error("unsupported auth policy")
    password = None
    if namespace.password_env is not None:
        if auth != "password":
            parser.error("--password-env requires --auth password")
        password = os.environ.get(namespace.password_env)
        if password is None:
            parser.error(f"environment variable is not set: {namespace.password_env}")
    transports = None
    if namespace.transports is not None:
        transports = set(namespace.transports)
    return _CLIOptions(
        auth=auth,
        clean_before_start=namespace.clean_before_start,
        client=namespace.client,
        data_directory=namespace.data_directory,
        database=namespace.database,
        install_db=namespace.install_db,
        mariadbd=namespace.mariadbd,
        password=password,
        port=namespace.port,
        reset_database=namespace.reset_database,
        server_args=tuple(namespace.server_arg),
        socket_path=namespace.socket_path,
        startup_timeout=namespace.startup_timeout,
        transports=transports,
        user=namespace.user,
    )


def _render_client_commands(
    *,
    client: str | Path,
    server: TemporaryMariaDBServer,
) -> tuple[str, ...]:
    """Render one ready-to-copy mariadb command for each public transport."""

    commands: list[str] = []
    if "unix_socket" in server.transports and server.socket_path is not None:
        commands.append(
            MariaDBClientCommand(
                auth=server.auth,
                client=client,
                database=server.database,
                host=None,
                password=server.password,
                port=None,
                socket_path=server.socket_path,
                transport="unix_socket",
                user=server.user,
            ).shell_command()
        )
    if (
        "tcp" in server.transports
        and server.host is not None
        and server.port is not None
    ):
        commands.append(
            MariaDBClientCommand(
                auth=server.auth,
                client=client,
                database=server.database,
                host=server.host,
                password=server.password,
                port=server.port,
                socket_path=None,
                transport="tcp",
                user=server.user,
            ).shell_command()
        )
    return tuple(commands)


async def _run(argv: list[str] | None) -> int:
    """Run the foreground server until interrupted by the user."""

    options = _parse_options(argv)
    async with temporary_mariadb_server(
        auth=options.auth,
        clean_before_start=options.clean_before_start,
        client=options.client,
        data_directory=options.data_directory,
        database=options.database,
        install_db=options.install_db,
        mariadbd=options.mariadbd,
        password=options.password,
        port=options.port,
        reset_database=options.reset_database,
        server_args=options.server_args,
        socket_path=options.socket_path,
        startup_timeout=options.startup_timeout,
        transports=options.transports,
        user=options.user,
    ) as server:
        for command in _render_client_commands(client=options.client, server=server):
            print(command, file=sys.stdout)
        print("Temporary MariaDB test server ready.", file=sys.stderr)
        print(f"data_directory: {server.data_directory}", file=sys.stderr)
        if server.auth == "password":
            print(f"password: {server.password}", file=sys.stderr)
        print("Press Ctrl-C to stop.", file=sys.stderr)
        stop_event = asyncio.Event()
        _ = await stop_event.wait()
        return 0


def main(argv: list[str] | None = None) -> int:
    """Run the `snekql-mariadb-server` foreground CLI."""

    try:
        return asyncio.run(_run(argv))
    except KeyboardInterrupt:
        return 130
    except TemporaryMariaDBServerError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
