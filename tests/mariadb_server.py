"""Shared MariaDB server fixture for integration tests."""

from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from snektest import session_fixture


@dataclass(frozen=True)
class MariaDBCommandResult:
    """Captured result from a MariaDB command-line client invocation."""

    returncode: int
    stderr: str
    stdout: str


@dataclass(frozen=True)
class MariaDBServer:
    """Connection details for a local unprivileged MariaDB test server."""

    database: str
    data_directory: Path
    host: str
    port: int
    socket_path: Path
    user: str

    def run_sql(self, sql: str) -> MariaDBCommandResult:
        """Execute SQL against the local test server through the MariaDB CLI."""

        return _run_command(
            "mariadb",
            "--protocol=tcp",
            "-h",
            self.host,
            "-P",
            str(self.port),
            "-u",
            self.user,
            "-e",
            sql,
        )


def _find_free_tcp_port() -> int:
    """Reserve a local TCP port long enough to learn an available number."""

    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


def _run_command(*args: str) -> MariaDBCommandResult:
    """Run a command and fail tests with captured diagnostics."""

    completed_process = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )
    result = MariaDBCommandResult(
        returncode=completed_process.returncode,
        stderr=completed_process.stderr,
        stdout=completed_process.stdout,
    )
    if result.returncode != 0:
        command = " ".join(args)
        msg = f"command failed: {command}\n{result.stderr}"
        raise AssertionError(msg)
    return result


def _initialize_data_directory(data_directory: Path) -> None:
    """Create an isolated MariaDB data directory for a throwaway server."""

    _ = _run_command(
        "mariadb-install-db",
        "--no-defaults",
        f"--datadir={data_directory}",
        "--auth-root-authentication-method=normal",
        "--skip-test-db",
    )


def _start_process(
    *,
    data_directory: Path,
    error_log_path: Path,
    pid_path: Path,
    port: int,
    socket_path: Path,
) -> subprocess.Popen[bytes]:
    """Start mariadbd without reading global configuration files."""

    return subprocess.Popen(
        [
            "mariadbd",
            "--no-defaults",
            f"--datadir={data_directory}",
            f"--socket={socket_path}",
            f"--pid-file={pid_path}",
            f"--port={port}",
            "--bind-address=127.0.0.1",
            "--skip-grant-tables",
            "--skip-networking=0",
            f"--log-error={error_log_path}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate the test server and avoid leaving a child process behind."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        _ = process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        process.kill()
        _ = process.wait()


def _wait_until_ready(
    *,
    error_log_path: Path,
    process: subprocess.Popen[bytes],
    server: MariaDBServer,
) -> None:
    """Poll the MariaDB CLI until the server accepts local TCP connections."""

    for _ in range(80):
        if process.poll() is not None:
            error_log = error_log_path.read_text() if error_log_path.exists() else ""
            msg = f"mariadbd exited before becoming ready\n{error_log}"
            raise AssertionError(msg)
        try:
            _ = server.run_sql("SELECT 1")
        except AssertionError:
            time.sleep(0.25)
        else:
            return
    error_log = error_log_path.read_text() if error_log_path.exists() else ""
    msg = f"mariadbd did not become ready\n{error_log}"
    raise AssertionError(msg)


@session_fixture()
def provide_mariadb_server() -> Generator[MariaDBServer]:
    """Provide one local MariaDB server shared by medium integration tests."""

    with TemporaryDirectory(prefix="snekql-mariadb-") as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        data_directory = temporary_directory / "data"
        socket_path = temporary_directory / "mariadb.sock"
        pid_path = temporary_directory / "mariadb.pid"
        error_log_path = temporary_directory / "mariadb.err"
        server = MariaDBServer(
            database="snekql_test",
            data_directory=data_directory,
            host="127.0.0.1",
            port=_find_free_tcp_port(),
            socket_path=socket_path,
            user="root",
        )
        _initialize_data_directory(data_directory)
        process = _start_process(
            data_directory=data_directory,
            error_log_path=error_log_path,
            pid_path=pid_path,
            port=server.port,
            socket_path=socket_path,
        )
        try:
            _wait_until_ready(
                error_log_path=error_log_path,
                process=process,
                server=server,
            )
            _ = server.run_sql(f"CREATE DATABASE {server.database}")
            yield server
        finally:
            _stop_process(process)
