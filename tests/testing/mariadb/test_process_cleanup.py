"""Public temporary-server failures release their subprocesses."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import anyio
from snektest import (
    Param,
    assert_eq,
    assert_in,
    assert_is,
    assert_is_not_none,
    assert_raises,
    assert_true,
    test,
)

from snekql.testing.mariadb import TemporaryMariaDBServerError, temporary_mariadb_server


@test(mark="medium")
async def reset_failure_reaps_server_before_entry_raises() -> None:
    """Failed pre-yield reset retains a reusable directory, not a live server."""

    processes: list[asyncio.subprocess.Process] = []
    spawn = asyncio.create_subprocess_exec

    async def record(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Observe the external process boundary without replacing MariaDB."""
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process

    with TemporaryDirectory() as directory:
        client = Path(directory) / "client"
        real_client = which("mariadb")
        assert_is_not_none(real_client)
        await asyncio.to_thread(
            client.write_text,
            f"""#!/usr/bin/env python3
import os, sys
if "snekql_views_to_drop" in sys.argv[-1]:
    print("injected reset failure", file=sys.stderr)
    sys.exit(7)
os.execv({real_client!r}, [{real_client!r}, *sys.argv[1:]])
""",
        )
        await asyncio.to_thread(client.chmod, 0o700)
        data_directory = Path(directory) / "data"
        try:
            with (
                patch("asyncio.create_subprocess_exec", record),
                assert_raises(TemporaryMariaDBServerError),
            ):
                async with temporary_mariadb_server(
                    data_directory=data_directory,
                    client=client,
                    reset_database=True,
                ):
                    assert_true(False, msg="reset failure must precede yield")
            assert_true(all(process.returncode is not None for process in processes))
            assert_true(await asyncio.to_thread(data_directory.is_dir))
            async with temporary_mariadb_server(
                data_directory=data_directory
            ) as server:
                assert_eq((await server.run_sql("SELECT 1")).returncode, 0)
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()


class _CancellationGate:
    """Controlled external subprocess operations, with real operating-system children."""

    def __init__(self, phase: str) -> None:
        self.phase: str = phase
        self.create: Callable[..., Awaitable[asyncio.subprocess.Process]] = (
            asyncio.create_subprocess_exec
        )
        self.processes: list[asyncio.subprocess.Process] = []
        self.reached: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()

    async def spawn(self, *args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Delay real process operations only at the external subprocess boundary."""
        is_server = args[0] == "mariadbd"
        blocked = (
            (self.phase == "installer" and args[0] == "mariadb-install-db")
            or (self.phase == "readiness" and args[-1] == "SELECT 1")
            or (
                self.phase == "bootstrap"
                and args[0] == "mariadb"
                and kwargs.get("stdin") == asyncio.subprocess.PIPE
            )
            or (self.phase == "reset" and "snekql_views_to_drop" in args[-1])
            or (self.phase == "sql" and args[-1] == "SELECT SLEEP(60)")
        )
        command = (
            (sys.executable, "-c", "import time; time.sleep(60)") if blocked else args
        )
        process = await self.create(*command, **kwargs)
        self.processes.append(process)
        if blocked:
            communicate = process.communicate

            async def observe(stdin_data: bytes | None = None) -> tuple[bytes, bytes]:
                self.reached.set()
                return await communicate(stdin_data)

            object.__setattr__(process, "communicate", observe)
        if is_server and self.phase == "spawn":
            self.reached.set()
            await self.release.wait()
        if is_server and self.phase == "exit":
            wait = process.wait

            async def held_wait() -> int:
                self.reached.set()
                await self.release.wait()
                return await wait()

            object.__setattr__(process, "wait", held_wait)
        return process


@test(
    [
        Param(value=(phase, mode), name=f"{phase}_{mode}")
        for phase in (
            "installer",
            "readiness",
            "bootstrap",
            "reset",
            "sql",
            "spawn",
            "exit",
        )
        for mode in ("native", "anyio")
    ],
    mark="medium",
)
async def cancellation_reaps_owned_children(case: tuple[str, str]) -> None:
    """Cancellation at each public lifecycle stage leaves no running child."""

    phase, mode = case
    gate = _CancellationGate(phase)
    scope = anyio.CancelScope()

    async def run(data_directory: Path) -> None:
        with scope:
            async with temporary_mariadb_server(
                data_directory=data_directory,
                auth="password" if phase == "bootstrap" else "insecure",
                reset_database=phase == "reset",
            ) as server:
                if phase == "sql":
                    await server.run_sql("SELECT SLEEP(60)")
                else:
                    assert_eq(phase, "exit")

    with (
        TemporaryDirectory() as directory,
        patch("asyncio.create_subprocess_exec", gate.spawn),
    ):
        task = asyncio.create_task(run(Path(directory) / "data"))
        try:
            await asyncio.wait_for(gate.reached.wait(), 10)
            if mode == "native":
                task.cancel("first cancellation")
                await asyncio.sleep(0)
                task.cancel("repeated cancellation")
            else:
                scope.cancel()
            gate.release.set()
            if mode == "native":
                with assert_raises(asyncio.CancelledError) as error:
                    await task
                assert_eq(str(error.exception), "first cancellation")
            else:
                await task
            assert_true(
                all(process.returncode is not None for process in gate.processes)
            )
        finally:
            gate.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for process in gate.processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()


class _ReadinessError(Exception):
    """Unexpected external client failure used to check primary-error preservation."""


@test(
    [
        Param(value="allow", name="cleanup_ok"),
        Param(value="deny", name="cleanup_denied"),
    ],
    mark="medium",
)
async def readiness_error_remains_primary(policy: str) -> None:
    """Even a failed stop cannot replace the original pre-yield exception."""

    spawn = asyncio.create_subprocess_exec
    signal_group = os.killpg
    processes: list[asyncio.subprocess.Process] = []
    denied: set[int] = set()
    failure = _ReadinessError("injected readiness failure")
    signal_failure = PermissionError("injected signal refusal")

    async def record(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """A real CLI child fails at communicate rather than returning a status."""
        if args[-1] != "SELECT 1":
            process = await spawn(*args, **kwargs)
        else:
            process = await spawn(
                sys.executable, "-c", "import time; time.sleep(60)", **kwargs
            )
            communicate = process.communicate
            first = True

            async def fail_once(stdin_data: bytes | None = None) -> tuple[bytes, bytes]:
                nonlocal first
                if first:
                    first = False
                    raise failure
                return await communicate(stdin_data)

            object.__setattr__(process, "communicate", fail_once)
            denied.add(process.pid)
        processes.append(process)
        return process

    def deny_signal(pid: int, signal: int) -> None:
        """Simulate an operating-system refusal for only the selected child."""
        if policy == "deny" and pid in denied:
            raise signal_failure
        signal_group(pid, signal)

    with TemporaryDirectory() as directory:
        try:
            with (
                patch("asyncio.create_subprocess_exec", record),
                patch("os.killpg", deny_signal),
                assert_raises(_ReadinessError) as error,
            ):
                async with temporary_mariadb_server(
                    data_directory=Path(directory) / "data"
                ):
                    assert_true(False)
            assert_is(error.exception, failure)
            if policy == "deny":
                assert_in("child-process cleanup failed", " ".join(failure.__notes__))
            else:
                assert_true(
                    all(process.returncode is not None for process in processes)
                )
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()


@test(mark="medium")
async def terminate_resistant_server_is_killed() -> None:
    """A real child ignoring SIGTERM is killed after the unchanged ten-second grace."""

    spawn = asyncio.create_subprocess_exec
    processes: list[asyncio.subprocess.Process] = []
    with TemporaryDirectory() as directory:
        ready = Path(directory) / "ready"
        data_directory = Path(directory) / "data"
        await asyncio.to_thread((data_directory / "mysql").mkdir, parents=True)

        async def record(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
            """Use executable stand-ins; exercise real kernel signals and waitpid."""
            script = (
                f"import signal, time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path({str(ready)!r}).touch(); time.sleep(60)"
                if args[0] == "mariadbd"
                else "pass"
            )
            process = await spawn(sys.executable, "-c", script, **kwargs)
            processes.append(process)
            return process

        try:
            with patch("asyncio.create_subprocess_exec", record):
                async with temporary_mariadb_server(data_directory=data_directory):
                    with anyio.fail_after(5):
                        # Readiness comes from another process, not an asyncio task.
                        while not await asyncio.to_thread(ready.exists):  # noqa: ASYNC110
                            await asyncio.sleep(0.01)
            assert_eq(processes[0].returncode, -9)
            assert_true(all(process.returncode is not None for process in processes))
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()


@test(mark="fast")
async def server_spawn_failure_is_a_domain_error() -> None:
    """Missing server executables retain the public startup error contract."""

    with TemporaryDirectory() as directory:
        data_directory = Path(directory) / "data"
        await asyncio.to_thread((data_directory / "mysql").mkdir, parents=True)
        with assert_raises(TemporaryMariaDBServerError) as error:
            async with temporary_mariadb_server(
                data_directory=data_directory, mariadbd=Path(directory) / "absent"
            ):
                assert_true(False)

    assert_in("failed to start mariadbd", str(error.exception))
