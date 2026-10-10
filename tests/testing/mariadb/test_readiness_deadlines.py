"""Readiness budgets bound real client subprocesses through the public server API."""

import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Literal

import anyio
from snektest import (
    Param,
    assert_in,
    assert_lt,
    assert_raises,
    assert_true,
    fixture,
    load_fixture,
    test,
)

from snekql.testing.mariadb import TemporaryMariaDBServerError, temporary_mariadb_server


@dataclass(frozen=True)
class ExecutableAdapters:
    """Local executable stand-ins recording the children owned by startup."""

    client: Path
    data_directory: Path
    pid_log: Path
    server: Path


@fixture
async def readiness_adapters(
    delay: float, exit_code: int, phase: str
) -> AsyncGenerator[ExecutableAdapters]:
    """Exercise subprocess IO without requiring an installed MariaDB server."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        adapters = ExecutableAdapters(
            client=root / "client",
            data_directory=root / "data",
            pid_log=root / "pids",
            server=root / "server",
        )
        await asyncio.to_thread((adapters.data_directory / "mysql").mkdir, parents=True)
        await asyncio.to_thread(
            adapters.server.write_text,
            f"""#!{sys.executable}
import os, time
from pathlib import Path
with Path({str(adapters.pid_log)!r}).open('a') as log:
    log.write(str(os.getpid()) + '\\n')
time.sleep(60)
""",
        )
        await asyncio.to_thread(
            adapters.client.write_text,
            f"""#!{sys.executable}
import os, sys, time
from pathlib import Path
with Path({str(adapters.pid_log)!r}).open('a') as log:
    log.write(str(os.getpid()) + '\\n')
if sys.argv[-1] == 'SELECT 1':
    counter = Path({str(root / "probes")!r})
    probe = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(probe))
    if {phase!r} != 'password_final' or probe > 1:
        time.sleep({delay!r})
        sys.exit({exit_code!r})
if '-e' not in sys.argv:
    sys.stdin.read()
""",
        )
        await asyncio.to_thread(adapters.server.chmod, 0o700)
        await asyncio.to_thread(adapters.client.chmod, 0o700)
        try:
            yield adapters
        finally:
            if await asyncio.to_thread(adapters.pid_log.exists):
                child_pids = await asyncio.to_thread(adapters.pid_log.read_text)
                for child_pid in child_pids.splitlines():
                    with assert_raises(ProcessLookupError):
                        await asyncio.to_thread(os.kill, int(child_pid), 0)


@test(
    [
        Param(value=(delay, exit_code), name=name)
        for delay, exit_code, name in (
            (60.0, 0, "stalled"),
            (1.5, 1, "late_failure"),
            (1.5, 0, "late_success"),
            (0.0, 1, "retry_failure"),
        )
    ],
    [
        Param(value=phase, name=phase)
        for phase in ("insecure", "password_bootstrap", "password_final")
    ],
    mark="slow",
)
async def readiness_probe_obeys_remaining_budget(
    case: tuple[float, int], phase: str
) -> None:
    """Stalled or overdue probes cannot extend normal or password readiness."""
    adapters = await load_fixture(readiness_adapters(*case, phase))
    auth: Literal["insecure", "password"] = (
        "insecure" if phase == "insecure" else "password"
    )

    started = monotonic()
    with anyio.fail_after(5), assert_raises(TemporaryMariaDBServerError) as error:
        async with temporary_mariadb_server(
            data_directory=adapters.data_directory,
            mariadbd=adapters.server,
            client=adapters.client,
            auth=auth,
            startup_timeout=0.15,
        ):
            assert_true(False, msg="overdue readiness must not yield a server")
    elapsed = monotonic() - started

    assert_in("mariadbd did not become ready", str(error.exception))
    assert_lt(elapsed, 1.0)
    assert_true(await asyncio.to_thread((adapters.data_directory / "mysql").is_dir))


@test(
    [
        Param[Literal["insecure", "password"]](value="insecure", name="insecure"),
        Param[Literal["insecure", "password"]](value="password", name="password"),
    ],
    mark="slow",
)
async def prompt_readiness_succeeds(auth: Literal["insecure", "password"]) -> None:
    """Prompt successful probes still allow entering the server context."""
    adapters = await load_fixture(readiness_adapters(0.0, 0, "prompt"))

    async with temporary_mariadb_server(
        data_directory=adapters.data_directory,
        mariadbd=adapters.server,
        client=adapters.client,
        auth=auth,
        startup_timeout=5,
    ) as server:
        assert_true(server.data_directory == adapters.data_directory)


@test(
    [Param(value="native", name="native"), Param(value="anyio", name="anyio")],
    mark="slow",
)
async def cancelled_readiness_reaps_children(mode: str) -> None:
    """External cancellation still releases a stalled readiness client and server."""
    adapters = await load_fixture(readiness_adapters(60.0, 0, "insecure"))
    scope = anyio.CancelScope()

    async def start_server() -> None:
        with scope:
            async with temporary_mariadb_server(
                data_directory=adapters.data_directory,
                mariadbd=adapters.server,
                client=adapters.client,
                startup_timeout=60,
            ):
                assert_true(False, msg="stalled client must not publish readiness")

    task = asyncio.create_task(start_server())
    try:
        with anyio.fail_after(5):
            while True:
                if await asyncio.to_thread(adapters.pid_log.exists):
                    child_pids = await asyncio.to_thread(adapters.pid_log.read_text)
                    if len(child_pids.splitlines()) == 2:
                        break
                await asyncio.sleep(0.01)
        if mode == "native":
            task.cancel("first cancellation")
            await asyncio.sleep(0)
            task.cancel("repeated cancellation")
            with assert_raises(asyncio.CancelledError):
                await task
        else:
            scope.cancel()
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
