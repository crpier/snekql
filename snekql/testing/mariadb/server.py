"""Temporary MariaDB Test Server support for integration tests."""

from __future__ import annotations

import asyncio
import os
import secrets
import shlex
import shutil
import socket
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal

from snekql import mariadb
from snekql.errors import SnekqlError

type MariaDBAuth = Literal["insecure", "password"]
type MariaDBTransport = Literal["unix_socket", "tcp"]

_DEFAULT_DATABASE = "test"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_TRANSPORTS: frozenset[MariaDBTransport] = frozenset({"unix_socket"})
_IDENTIFIER_MAX_LENGTH = 64
_MANAGED_SERVER_OPTIONS = frozenset(
    {
        "--bind-address",
        "--datadir",
        "--log-error",
        "--no-defaults",
        "--pid-file",
        "--port",
        "--skip-grant-tables",
        "--skip-networking",
        "--socket",
    }
)
_RESET_DATABASE_SQL = """
SET SESSION group_concat_max_len = 1000000;
SET FOREIGN_KEY_CHECKS = 0;
SELECT GROUP_CONCAT(CONCAT('`', REPLACE(TABLE_NAME, '`', '``'), '`'))
INTO @snekql_tables_to_drop
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_TYPE = 'BASE TABLE';
SET @snekql_drop_tables = IF(
    @snekql_tables_to_drop IS NULL,
    'DO 0',
    CONCAT('DROP TABLE ', @snekql_tables_to_drop)
);
PREPARE snekql_drop_tables_statement FROM @snekql_drop_tables;
EXECUTE snekql_drop_tables_statement;
DEALLOCATE PREPARE snekql_drop_tables_statement;
SET FOREIGN_KEY_CHECKS = 1;
"""
_SHUTDOWN_TIMEOUT = 10.0


@dataclass(frozen=True, kw_only=True)
class MariaDBCommandResult:
    """Captured result from a MariaDB command-line client invocation."""

    returncode: int
    stderr: str
    stdout: str


class TemporaryMariaDBServerError(SnekqlError):
    """Failure while managing a local Temporary MariaDB Test Server."""


@dataclass(frozen=True, kw_only=True)
class MariaDBClientCommand:
    """Build executable and renderable MariaDB client commands."""

    auth: MariaDBAuth
    client: str | Path
    database: str | None
    host: str | None
    password: str
    port: int | None
    socket_path: Path | None
    transport: MariaDBTransport
    user: str

    def arguments(self, *, password_prompt: bool = False) -> tuple[str, ...]:
        """Build argv while keeping transport rules in one module."""

        arguments = [str(self.client)]
        if self.transport == "unix_socket":
            if self.socket_path is None:
                msg = "unix_socket client command requires socket_path"
                raise TemporaryMariaDBServerError(msg)
            arguments.extend(("--socket", str(self.socket_path)))
        else:
            if self.host is None or self.port is None:
                msg = "tcp client command requires host and port"
                raise TemporaryMariaDBServerError(msg)
            arguments.extend(("--protocol=tcp", "-h", self.host, "-P", str(self.port)))
        arguments.extend(("-u", self.user))
        if self.auth == "password" and password_prompt:
            arguments.append("-p")
        if self.database is not None:
            arguments.extend(("-D", self.database))
        return tuple(arguments)

    def environment(self) -> Mapping[str, str] | None:
        """Provide password credentials without exposing them in argv."""

        if self.auth != "password":
            return None
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = self.password
        return environment

    def shell_command(self) -> str:
        """Render a ready-to-copy interactive client command."""

        return " ".join(
            shlex.quote(argument) for argument in self.arguments(password_prompt=True)
        )


@dataclass(frozen=True, kw_only=True)
class TemporaryMariaDBServer:
    """Connection details for a local Temporary MariaDB Test Server.

    >>> server = TemporaryMariaDBServer(
    ...     auth="insecure",
    ...     database="test",
    ...     data_directory=Path("data"),
    ...     error_log_path=Path("mariadb.err"),
    ...     host=None,
    ...     password="",
    ...     pid_path=Path("mariadb.pid"),
    ...     port=None,
    ...     socket_path=Path("mariadb.sock"),
    ...     transports=frozenset({"unix_socket"}),
    ...     user="root",
    ... )
    >>> server.config().unix_socket
    PosixPath('mariadb.sock')
    """

    auth: MariaDBAuth
    database: str
    data_directory: Path
    error_log_path: Path
    host: str | None
    password: str
    pid_path: Path
    port: int | None
    socket_path: Path | None
    transports: frozenset[MariaDBTransport]
    user: str
    _client: str | Path = field(
        default="mariadb",
        init=False,
        repr=False,
        compare=False,
    )

    def config(
        self,
        *,
        transport: MariaDBTransport | None = None,
        pool_size: int = 5,
        acquire_timeout: float = 30.0,
        charset: str = "utf8mb4",
    ) -> mariadb.Config:
        """Build a snekql MariaDB runtime config for this test server."""

        selected_transport = self._select_transport(transport)
        if selected_transport == "unix_socket":
            if self.socket_path is None:
                msg = (
                    "Temporary MariaDB Test Server did not expose unix_socket transport"
                )
                raise TemporaryMariaDBServerError(msg)
            return mariadb.Config(
                acquire_timeout=acquire_timeout,
                charset=charset,
                database=self.database,
                password=self.password,
                pool_size=pool_size,
                unix_socket=self.socket_path,
                user=self.user,
            )
        if self.host is None or self.port is None:
            msg = "Temporary MariaDB Test Server did not expose tcp transport"
            raise TemporaryMariaDBServerError(msg)
        return mariadb.Config(
            acquire_timeout=acquire_timeout,
            charset=charset,
            database=self.database,
            host=self.host,
            password=self.password,
            pool_size=pool_size,
            port=self.port,
            user=self.user,
        )

    async def reset_database(
        self,
        *,
        transport: MariaDBTransport | None = None,
    ) -> None:
        """Drop all base tables from the configured test database."""

        _ = await self.run_sql(_RESET_DATABASE_SQL, transport=transport)

    async def run_sql(
        self,
        sql: str,
        *,
        transport: MariaDBTransport | None = None,
        check: bool = True,
    ) -> MariaDBCommandResult:
        """Execute SQL through the MariaDB command-line client."""

        selected_transport = self._select_transport(transport)
        result = await _run_client_sql(
            auth=self.auth,
            client=self._client,
            database=self.database,
            host=self.host,
            password=self.password,
            port=self.port,
            socket_path=self.socket_path,
            sql=sql,
            transport=selected_transport,
            user=self.user,
        )
        if check and result.returncode != 0:
            msg = f"mariadb command failed while executing SQL\n{result.stderr}"
            raise TemporaryMariaDBServerError(msg)
        return result

    def _select_transport(self, transport: MariaDBTransport | None) -> MariaDBTransport:
        """Prefer Unix socket while rejecting disabled explicit transports."""

        if transport is None:
            if "unix_socket" in self.transports:
                return "unix_socket"
            if "tcp" in self.transports:
                return "tcp"
            msg = "Temporary MariaDB Test Server has no enabled transports"
            raise TemporaryMariaDBServerError(msg)
        if transport not in {"unix_socket", "tcp"}:
            msg = f"unsupported MariaDB test-server transport: {transport!r}"
            raise TemporaryMariaDBServerError(msg)
        if transport not in self.transports:
            msg = f"Temporary MariaDB Test Server did not expose {transport} transport"
            raise TemporaryMariaDBServerError(msg)
        return transport


@dataclass(frozen=True, kw_only=True)
class _ProcessPaths:
    """Filesystem paths that tie one mariadbd process lifecycle together."""

    data_directory: Path
    error_log_path: Path
    internal_socket_path: Path
    pid_path: Path
    public_socket_path: Path | None
    runtime_directory: Path


@dataclass(frozen=True, kw_only=True)
class _TemporaryMariaDBServerOptions:
    """Validated startup options for a Temporary MariaDB Test Server."""

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
    transports: frozenset[MariaDBTransport]
    user: str


@dataclass(frozen=True, kw_only=True)
class _StartupPlan:
    """Resolved lifecycle facts for one Temporary MariaDB Test Server run."""

    options: _TemporaryMariaDBServerOptions
    password: str
    paths: _ProcessPaths
    port: int | None
    readiness_transport: MariaDBTransport

    def server(self) -> TemporaryMariaDBServer:
        """Build the public server value from resolved startup facts."""

        server = TemporaryMariaDBServer(
            auth=self.options.auth,
            database=self.options.database,
            data_directory=self.paths.data_directory,
            error_log_path=self.paths.error_log_path,
            host=_DEFAULT_HOST if "tcp" in self.options.transports else None,
            password=self.password,
            pid_path=self.paths.pid_path,
            port=self.port,
            socket_path=self.paths.public_socket_path,
            transports=self.options.transports,
            user=self.options.user,
        )
        object.__setattr__(server, "_client", self.options.client)
        return server

    @property
    def tcp_enabled(self) -> bool:
        """Whether this plan exposes local TCP transport."""

        return "tcp" in self.options.transports


def _resolve_user_path(path: Path) -> Path:
    """Make caller-provided paths stable for MariaDB helper processes."""

    return path.expanduser().resolve()


async def _create_process_paths(
    options: _TemporaryMariaDBServerOptions,
) -> _ProcessPaths:
    """Create retained runtime paths without deleting them at shutdown."""

    runtime_directory = Path(mkdtemp(prefix="snekql-mariadb-"))
    data_directory = (
        _resolve_user_path(options.data_directory)
        if options.data_directory is not None
        else runtime_directory / "data"
    )
    public_socket_path = None
    if "unix_socket" in options.transports:
        public_socket_path = (
            _resolve_user_path(options.socket_path)
            if options.socket_path is not None
            else runtime_directory / "mariadb.sock"
        )
    internal_socket_path = public_socket_path or runtime_directory / "internal.sock"
    return _ProcessPaths(
        data_directory=data_directory,
        error_log_path=runtime_directory / "mariadb.err",
        internal_socket_path=internal_socket_path,
        pid_path=runtime_directory / "mariadb.pid",
        public_socket_path=public_socket_path,
        runtime_directory=runtime_directory,
    )


async def _ensure_data_directory(
    *,
    options: _TemporaryMariaDBServerOptions,
    paths: _ProcessPaths,
) -> None:
    """Initialize missing/empty data directories and reject invalid reuse."""

    if options.clean_before_start and paths.data_directory.exists():
        await asyncio.to_thread(shutil.rmtree, paths.data_directory)
    if not paths.data_directory.exists():
        await asyncio.to_thread(paths.data_directory.mkdir, parents=True)
        await _initialize_data_directory(options=options, paths=paths)
        return
    children = await asyncio.to_thread(lambda: tuple(paths.data_directory.iterdir()))
    if len(children) == 0:
        await _initialize_data_directory(options=options, paths=paths)
        return
    if (paths.data_directory / "mysql").is_dir():
        return
    msg = f"MariaDB data_directory is not empty and does not look initialized: {paths.data_directory}"
    raise TemporaryMariaDBServerError(msg)


async def _build_startup_plan(
    options: _TemporaryMariaDBServerOptions,
) -> _StartupPlan:
    """Resolve one startup plan before process lifecycle work begins."""

    paths = await _create_process_paths(options)
    await _ensure_data_directory(options=options, paths=paths)
    password = options.password or (
        secrets.token_urlsafe(24) if options.auth == "password" else ""
    )
    port = None
    if "tcp" in options.transports:
        port = options.port or _find_free_tcp_port()
    readiness_transport: MariaDBTransport = (
        "unix_socket" if "unix_socket" in options.transports else "tcp"
    )
    return _StartupPlan(
        options=options,
        password=password,
        paths=paths,
        port=port,
        readiness_transport=readiness_transport,
    )


def _is_quota_limited_install_error(stderr: str) -> bool:
    """Recognize MariaDB's quota-exhaustion initialization failure."""

    return "error 122" in stderr and "preallocating" in stderr


async def _initialize_data_directory(
    *,
    options: _TemporaryMariaDBServerOptions,
    paths: _ProcessPaths,
) -> None:
    """Create MariaDB system tables in a retained data directory."""

    result = await _run_command(
        str(options.install_db),
        "--no-defaults",
        f"--datadir={paths.data_directory}",
        "--auth-root-authentication-method=normal",
        "--skip-test-db",
    )
    if result.returncode != 0:
        message = f"mariadb-install-db failed\n{result.stderr}"
        if _is_quota_limited_install_error(result.stderr):
            message += (
                "\nMariaDB reported error 122 while preallocating files. "
                "This usually means the data_directory is on a full or "
                "quota-limited filesystem. Pass data_directory on a filesystem "
                "with enough free space, or clean retained temporary MariaDB "
                "data directories such as /tmp/snekql-mariadb-* before retrying."
            )
        raise TemporaryMariaDBServerError(message)


async def _start_process(
    *,
    options: _TemporaryMariaDBServerOptions,
    paths: _ProcessPaths,
    port: int | None,
    skip_grant_tables: bool,
    tcp_enabled: bool,
) -> asyncio.subprocess.Process:
    """Start mariadbd with managed local-test lifecycle arguments."""

    arguments = [
        str(options.mariadbd),
        "--no-defaults",
        f"--datadir={paths.data_directory}",
        f"--socket={paths.internal_socket_path}",
        f"--pid-file={paths.pid_path}",
        f"--log-error={paths.error_log_path}",
    ]
    if tcp_enabled:
        if port is None:
            msg = "internal error: TCP startup requires a port"
            raise TemporaryMariaDBServerError(msg)
        arguments.extend(
            (
                f"--port={port}",
                f"--bind-address={_DEFAULT_HOST}",
                "--skip-networking=0",
            )
        )
    else:
        arguments.append("--skip-networking=1")
    if skip_grant_tables:
        arguments.append("--skip-grant-tables")
    arguments.extend(options.server_args)
    try:
        return await asyncio.create_subprocess_exec(
            *arguments,
            stderr=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        msg = f"failed to start mariadbd: {error}"
        raise TemporaryMariaDBServerError(msg) from error


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Terminate a child server process without deleting retained data."""

    if process.returncode is not None:
        return
    process.terminate()
    try:
        _ = await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_TIMEOUT)
    except TimeoutError:
        process.kill()
        _ = await process.wait()


async def _wait_until_ready(  # noqa: PLR0913
    *,
    client: str | Path,
    database: str | None,
    host: str | None,
    password: str,
    port: int | None,
    process: asyncio.subprocess.Process,
    socket_path: Path | None,
    startup_timeout: float,
    transport: MariaDBTransport,
    user: str,
    auth: MariaDBAuth,
    error_log_path: Path,
) -> None:
    """Poll the MariaDB CLI until the server accepts local connections."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + startup_timeout
    while loop.time() < deadline:
        if process.returncode is not None:
            error_log = await _read_error_log(error_log_path)
            msg = f"mariadbd exited before becoming ready\n{error_log}"
            raise TemporaryMariaDBServerError(msg)
        result = await _run_client_sql(
            auth=auth,
            client=client,
            database=database,
            host=host,
            password=password,
            port=port,
            socket_path=socket_path,
            sql="SELECT 1",
            transport=transport,
            user=user,
        )
        if result.returncode == 0:
            return
        await asyncio.sleep(0.25)
    error_log = await _read_error_log(error_log_path)
    msg = f"mariadbd did not become ready\n{error_log}"
    raise TemporaryMariaDBServerError(msg)


async def _read_error_log(error_log_path: Path) -> str:
    """Read MariaDB's error log only when it exists."""

    exists = await asyncio.to_thread(error_log_path.exists)
    if not exists:
        return ""
    return await asyncio.to_thread(error_log_path.read_text)


async def _run_command(
    *arguments: str,
    env: Mapping[str, str] | None = None,
) -> MariaDBCommandResult:
    """Run one subprocess command and capture decoded output."""

    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            env=dict(env) if env is not None else None,
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        command = " ".join(arguments)
        msg = f"failed to run command: {command}: {error}"
        raise TemporaryMariaDBServerError(msg) from error
    stdout, stderr = await process.communicate()
    return MariaDBCommandResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stderr=stderr.decode(),
        stdout=stdout.decode(),
    )


async def _run_client_sql(  # noqa: PLR0913
    *,
    auth: MariaDBAuth,
    client: str | Path,
    database: str | None,
    host: str | None,
    password: str,
    port: int | None,
    socket_path: Path | None,
    sql: str,
    transport: MariaDBTransport,
    user: str,
) -> MariaDBCommandResult:
    """Execute SQL through the configured MariaDB CLI transport."""

    command = MariaDBClientCommand(
        auth=auth,
        client=client,
        database=database,
        host=host,
        password=password,
        port=port,
        socket_path=socket_path,
        transport=transport,
        user=user,
    )
    return await _run_command(
        *command.arguments(),
        "-e",
        sql,
        env=command.environment(),
    )


async def _create_database(
    *,
    plan: _StartupPlan,
    process: asyncio.subprocess.Process,
) -> None:
    """Create the requested test database after the server is reachable."""

    result = await _run_client_sql(
        auth=plan.options.auth,
        client=plan.options.client,
        database=None,
        host=_DEFAULT_HOST if plan.port is not None else None,
        password=plan.password,
        port=plan.port,
        socket_path=(
            plan.paths.internal_socket_path
            if plan.readiness_transport == "unix_socket"
            else None
        ),
        sql=f"CREATE DATABASE IF NOT EXISTS `{plan.options.database}`",
        transport=plan.readiness_transport,
        user=plan.options.user,
    )
    if result.returncode != 0:
        await _stop_process(process)
        msg = f"failed to create MariaDB test database\n{result.stderr}"
        raise TemporaryMariaDBServerError(msg)


async def _bootstrap_password_auth(plan: _StartupPlan) -> None:
    """Use a short insecure local bootstrap server to set password auth."""

    process = await _start_process(
        options=plan.options,
        paths=plan.paths,
        port=None,
        skip_grant_tables=True,
        tcp_enabled=False,
    )
    try:
        await _wait_until_ready(
            auth="insecure",
            client=plan.options.client,
            database=None,
            error_log_path=plan.paths.error_log_path,
            host=None,
            password="",
            port=None,
            process=process,
            socket_path=plan.paths.internal_socket_path,
            startup_timeout=plan.options.startup_timeout,
            transport="unix_socket",
            user="root",
        )
        bootstrap_sql = _password_bootstrap_sql(
            database=plan.options.database,
            password=plan.password,
            user=plan.options.user,
        )
        result = await _run_client_sql(
            auth="insecure",
            client=plan.options.client,
            database=None,
            host=None,
            password="",
            port=None,
            socket_path=plan.paths.internal_socket_path,
            sql=bootstrap_sql,
            transport="unix_socket",
            user="root",
        )
        if result.returncode != 0:
            msg = f"failed to bootstrap MariaDB password auth\n{result.stderr}"
            raise TemporaryMariaDBServerError(msg)
    finally:
        await _stop_process(process)


async def _start_ready_server(plan: _StartupPlan) -> asyncio.subprocess.Process:
    """Start the final server and wait on its preferred public transport."""

    process = await _start_process(
        options=plan.options,
        paths=plan.paths,
        port=plan.port,
        skip_grant_tables=plan.options.auth == "insecure",
        tcp_enabled=plan.tcp_enabled,
    )
    try:
        await _wait_until_ready(
            auth=plan.options.auth,
            client=plan.options.client,
            database=None,
            error_log_path=plan.paths.error_log_path,
            host=_DEFAULT_HOST if plan.readiness_transport == "tcp" else None,
            password=plan.password,
            port=plan.port if plan.readiness_transport == "tcp" else None,
            process=process,
            socket_path=(
                plan.paths.public_socket_path
                if plan.readiness_transport == "unix_socket"
                else None
            ),
            startup_timeout=plan.options.startup_timeout,
            transport=plan.readiness_transport,
            user=plan.options.user,
        )
        if plan.options.auth == "insecure":
            await _create_database(plan=plan, process=process)
    except TemporaryMariaDBServerError:
        await _stop_process(process)
        raise
    else:
        return process


@asynccontextmanager
async def _temporary_mariadb_server_context(
    options: _TemporaryMariaDBServerOptions,
) -> AsyncGenerator[TemporaryMariaDBServer]:
    """Manage the full MariaDB child process lifecycle."""

    plan = await _build_startup_plan(options)
    if options.auth == "password":
        await _bootstrap_password_auth(plan)
    process = await _start_ready_server(plan)
    server = plan.server()
    if options.reset_database:
        await server.reset_database()
    try:
        yield server
    finally:
        await _stop_process(process)


def _contains_managed_server_option(server_args: tuple[str, ...]) -> str | None:
    """Detect raw mariadbd arguments that would override managed behavior."""

    for argument in server_args:
        option = argument.split("=", maxsplit=1)[0]
        if option in _MANAGED_SERVER_OPTIONS:
            return option
    return None


def _find_free_tcp_port() -> int:
    """Reserve a local TCP port long enough to learn an available number."""

    with socket.socket() as server_socket:
        server_socket.bind((_DEFAULT_HOST, 0))
        return int(server_socket.getsockname()[1])


def _is_simple_identifier(value: str) -> bool:
    """Validate the intentionally narrow bootstrap identifier subset."""

    return 0 < len(value) <= _IDENTIFIER_MAX_LENGTH and all(
        character.isalnum() or character == "_" for character in value
    )


def _normalize_transports(
    transports: set[MariaDBTransport] | None,
) -> frozenset[MariaDBTransport]:
    """Normalize omitted transports to Unix socket and reject invalid values."""

    if transports is None:
        return _DEFAULT_TRANSPORTS
    normalized = frozenset(transports)
    if len(normalized) == 0:
        msg = "Temporary MariaDB Test Server requires at least one transport"
        raise TemporaryMariaDBServerError(msg)
    for transport in normalized:
        if transport not in {"unix_socket", "tcp"}:
            msg = f"unsupported MariaDB test-server transport: {transport!r}"
            raise TemporaryMariaDBServerError(msg)
    return normalized


def _password_bootstrap_sql(*, database: str, password: str, user: str) -> str:
    """Build idempotent bootstrap SQL for the narrow validated identifier set."""

    escaped_password = password.replace("'", "''")
    if user == "root":
        user_sql = f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{escaped_password}';"
    else:
        user_sql = "".join(
            (
                f"CREATE USER IF NOT EXISTS '{user}'@'localhost' IDENTIFIED BY '{escaped_password}';",
                f"ALTER USER '{user}'@'localhost' IDENTIFIED BY '{escaped_password}';",
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'localhost';",
                f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{escaped_password}';",
                f"ALTER USER '{user}'@'%' IDENTIFIED BY '{escaped_password}';",
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'%';",
            )
        )
    return "".join(
        (
            "FLUSH PRIVILEGES;",
            f"CREATE DATABASE IF NOT EXISTS `{database}`;",
            user_sql,
            "FLUSH PRIVILEGES;",
        )
    )


def _validate_options(options: _TemporaryMariaDBServerOptions) -> None:
    """Reject option combinations that cannot honor the public contract."""

    if options.auth not in {"insecure", "password"}:
        msg = f"unsupported MariaDB test-server auth policy: {options.auth!r}"
        raise TemporaryMariaDBServerError(msg)
    if options.clean_before_start and options.data_directory is None:
        msg = "clean_before_start requires data_directory"
        raise TemporaryMariaDBServerError(msg)
    if options.clean_before_start and options.reset_database:
        msg = "reset_database is incompatible with clean_before_start"
        raise TemporaryMariaDBServerError(msg)
    if options.port is not None and "tcp" not in options.transports:
        msg = "port requires tcp transport"
        raise TemporaryMariaDBServerError(msg)
    if options.socket_path is not None and "unix_socket" not in options.transports:
        msg = "socket_path requires unix_socket transport"
        raise TemporaryMariaDBServerError(msg)
    if options.password is not None and options.auth != "password":
        msg = "password requires auth='password'"
        raise TemporaryMariaDBServerError(msg)
    if not _is_simple_identifier(options.database):
        msg = "MariaDB database must be a non-empty alphanumeric or underscore identifier up to 64 characters"
        raise TemporaryMariaDBServerError(msg)
    if not _is_simple_identifier(options.user):
        msg = "MariaDB user must be a non-empty alphanumeric or underscore identifier up to 64 characters"
        raise TemporaryMariaDBServerError(msg)
    managed_option = _contains_managed_server_option(options.server_args)
    if managed_option is not None:
        msg = f"server_args contains managed mariadbd option: {managed_option}"
        raise TemporaryMariaDBServerError(msg)


def temporary_mariadb_server(  # noqa: PLR0913
    *,
    auth: MariaDBAuth = "insecure",
    transports: set[MariaDBTransport] | None = None,
    data_directory: Path | None = None,
    clean_before_start: bool = False,
    reset_database: bool = False,
    database: str = _DEFAULT_DATABASE,
    user: str = "root",
    password: str | None = None,
    port: int | None = None,
    socket_path: Path | None = None,
    server_args: tuple[str, ...] = (),
    mariadbd: str | Path = "mariadbd",
    install_db: str | Path = "mariadb-install-db",
    client: str | Path = "mariadb",
    startup_timeout: float = 20.0,
) -> AbstractAsyncContextManager[TemporaryMariaDBServer]:
    """Start a local Temporary MariaDB Test Server."""

    options = _TemporaryMariaDBServerOptions(
        auth=auth,
        clean_before_start=clean_before_start,
        client=client,
        data_directory=data_directory,
        database=database,
        install_db=install_db,
        mariadbd=mariadbd,
        password=password,
        port=port,
        reset_database=reset_database,
        server_args=server_args,
        socket_path=socket_path,
        startup_timeout=startup_timeout,
        transports=_normalize_transports(transports),
        user=user,
    )
    _validate_options(options)
    return _temporary_mariadb_server_context(options)


__all__ = [
    "MariaDBAuth",
    "MariaDBCommandResult",
    "MariaDBTransport",
    "TemporaryMariaDBServer",
    "TemporaryMariaDBServerError",
    "temporary_mariadb_server",
]
