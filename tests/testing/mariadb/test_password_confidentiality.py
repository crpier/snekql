"""Password bootstrap keeps credentials out of process arguments and diagnostics."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from traceback import format_exception
from typing import Any
from unittest.mock import patch

import anyio
from snektest import (
    Param,
    assert_eq,
    assert_in,
    assert_not_in,
    assert_raises,
    assert_true,
    load_fixture,
    test,
)

from snekql.testing.mariadb import TemporaryMariaDBServerError, temporary_mariadb_server
from tests.helpers import capture_snekql_logs, provide_mariadb_server

SENTINEL = "harmless_bootstrap_sentinel_323"


@test(mark="medium")
async def bootstrap_password_uses_stdin() -> None:
    """Observe real client arguments and stdin while bootstrapping usable credentials."""

    spawn = asyncio.create_subprocess_exec
    arguments: list[tuple[str, ...]] = []
    inputs: list[bytes] = []

    async def record(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Capture only the external subprocess invocation and its input pipe."""
        arguments.append(args)
        process = await spawn(*args, **kwargs)
        communicate = process.communicate

        async def observe(stdin_data: bytes | None = None) -> tuple[bytes, bytes]:
            if stdin_data is not None:
                inputs.append(stdin_data)
            return await communicate(stdin_data)

        object.__setattr__(process, "communicate", observe)
        return process

    with (
        TemporaryDirectory() as directory,
        patch("asyncio.create_subprocess_exec", record),
    ):
        async with temporary_mariadb_server(
            auth="password", password=SENTINEL, data_directory=Path(directory) / "data"
        ) as server:
            assert_eq((await server.run_sql("SELECT 1")).returncode, 0)

    assert_not_in(SENTINEL, repr(arguments))
    assert_not_in("IDENTIFIED BY", repr(arguments))
    assert_in(SENTINEL.encode(), b"".join(inputs))


@test(
    [
        Param(value=stage, name=stage)
        for stage in ("exec", "sql", "startup_log", "server_exec", "communicate")
    ],
    mark="medium",
)
async def startup_failures_do_not_echo_password(stage: str) -> None:
    """Treat exec errors, client statement echoes and retained server logs as sensitive."""

    spawn = asyncio.create_subprocess_exec

    async def inject(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Inject disclosure-bearing failures at the external process boundary."""
        if stage == "server_exec" and args[0] == "mariadbd":
            message = f"external server exec error including {SENTINEL}"
            raise OSError(message)
        if kwargs.get("stdin") == asyncio.subprocess.PIPE:
            if stage == "exec":
                message = f"external exec error including {SENTINEL}"
                raise OSError(message)
            if stage == "sql":
                return await spawn(
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.buffer.write(sys.stdin.buffer.read()); sys.exit(1)",
                    **kwargs,
                )
        if stage == "communicate" and kwargs.get("stdin") == asyncio.subprocess.PIPE:
            process = await spawn(
                sys.executable, "-c", "import time; time.sleep(60)", **kwargs
            )
            communicate = process.communicate
            fault = UnicodeError(SENTINEL)

            async def fail_input(
                stdin_data: bytes | None = None,
            ) -> tuple[bytes, bytes]:
                if stdin_data is not None:
                    raise fault
                return await communicate(stdin_data)

            object.__setattr__(process, "communicate", fail_input)
            return process
        if (
            stage == "startup_log"
            and args[0] == "mariadbd"
            and "--skip-grant-tables" not in args
        ):
            log_path = next(
                argument.split("=", 1)[1]
                for argument in args
                if argument.startswith("--log-error=")
            )
            await asyncio.to_thread(
                Path(log_path).write_text,
                f"server echoed ALTER USER IDENTIFIED BY '{SENTINEL}'",
            )
            return await spawn(sys.executable, "-c", "pass", **kwargs)
        return await spawn(*args, **kwargs)

    with (
        TemporaryDirectory() as directory,
        patch("asyncio.create_subprocess_exec", inject),
        capture_snekql_logs() as logs,
        assert_raises(TemporaryMariaDBServerError) as error,
    ):
        async with temporary_mariadb_server(
            auth="password",
            password=SENTINEL,
            data_directory=Path(directory) / "data",
        ):
            assert_true(False, msg="fault must prevent startup")

    assert_not_in(SENTINEL, "".join(format_exception(error.exception)))
    assert_not_in(SENTINEL, repr([record.getMessage() for record in logs.records]))


class _SensitiveClientGate:
    """Synchronize real client stdin and cleanup without patching package internals."""

    def __init__(self) -> None:
        self.create: Callable[..., Awaitable[asyncio.subprocess.Process]] = (
            asyncio.create_subprocess_exec
        )
        self.processes: list[asyncio.subprocess.Process] = []
        self.clients: list[asyncio.subprocess.Process] = []
        self.started: asyncio.Event = asyncio.Event()
        self.cleaning: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()

    async def spawn(self, *args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Hold a real sensitive client at communicate and its cleanup boundary."""
        sensitive = kwargs.get("stdin") == asyncio.subprocess.PIPE
        command = (
            (sys.executable, "-c", "import time; time.sleep(60)") if sensitive else args
        )
        process = await self.create(*command, **kwargs)
        self.processes.append(process)
        if sensitive:
            self.clients.append(process)
            communicate = process.communicate

            async def observe(stdin_data: bytes | None = None) -> tuple[bytes, bytes]:
                if stdin_data is not None:
                    assert_in(SENTINEL.encode(), stdin_data)
                    self.started.set()
                else:
                    self.cleaning.set()
                    await self.release.wait()
                return await communicate(stdin_data)

            object.__setattr__(process, "communicate", observe)
        return process


@test([Param(value=mode, name=mode) for mode in ("native", "anyio")], mark="medium")
async def cancelled_bootstrap_closes_sensitive_client(mode: str) -> None:
    """Cancellation closes stdin and reaps its client without echoing sensitive input."""

    gate = _SensitiveClientGate()
    scope = anyio.CancelScope()
    errors: list[str] = []

    async def enter(data_directory: Path) -> None:
        with scope:
            try:
                async with temporary_mariadb_server(
                    auth="password", password=SENTINEL, data_directory=data_directory
                ):
                    assert_true(False)
            except asyncio.CancelledError as error:
                errors.append("".join(format_exception(error)))
                raise

    with (
        TemporaryDirectory() as directory,
        patch("asyncio.create_subprocess_exec", gate.spawn),
        capture_snekql_logs() as logs,
    ):
        task = asyncio.create_task(enter(Path(directory) / "data"))
        try:
            await asyncio.wait_for(gate.started.wait(), 10)
            if mode == "native":
                task.cancel("first cancellation")
            else:
                scope.cancel()
            await asyncio.wait_for(gate.cleaning.wait(), 10)
            if mode == "native":
                task.cancel("repeated cancellation")
            gate.release.set()
            await asyncio.gather(task, return_exceptions=True)
            assert_eq(len(errors), 1)
            assert_eq(len(gate.clients), 1)
            assert_true(gate.clients[0].returncode is not None)
            assert gate.clients[0].stdin is not None
            assert_true(gate.clients[0].stdin.is_closing())
            assert_not_in(SENTINEL, repr(errors))
            assert_not_in(
                SENTINEL, repr([record.getMessage() for record in logs.records])
            )
        finally:
            gate.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for process in gate.processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()


@test(
    [
        Param(value=(user, password), name=f"{user}_{label}")
        for user in ("root", "named_test")
        for label, password in (
            ("generated", None),
            ("provided", "quoted ' test password"),
        )
    ],
    mark="medium",
)
async def bootstrap_credentials_remain_usable(case: tuple[str, str | None]) -> None:
    """Named/root credentials still work for generated and explicitly quoted passwords."""

    user, password = case
    with TemporaryDirectory() as directory:
        async with temporary_mariadb_server(
            auth="password",
            user=user,
            password=password,
            data_directory=Path(directory) / "data",
        ) as server:
            result = await server.run_sql("SELECT 1")

    assert_eq(result.returncode, 0)
    assert_true(bool(server.password))
    if password is not None:
        assert_eq(server.password, password)


@test(mark="medium")
async def raw_sql_result_is_unchanged() -> None:
    """The public SQL helper keeps its existing tabular command output."""

    server = await load_fixture(provide_mariadb_server())

    result = await server.run_sql("SELECT 'raw text' AS value; SELECT 2 AS second")

    assert_eq(
        (result.returncode, result.stdout),
        (0, "value\nraw text\nsecond\n2\n"),
    )


@test(mark="medium")
async def raw_sql_error_result_is_unchanged() -> None:
    """Explicit unchecked SQL still exposes the caller's command result."""

    server = await load_fixture(provide_mariadb_server())

    result = await server.run_sql("SELECT missing_column", check=False)

    assert_eq(result.returncode, 1)
    assert_in("Unknown column", result.stderr)
