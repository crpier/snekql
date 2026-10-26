"""Isolated public-server probe: real signals/reaping, controlled loop time only."""

import asyncio
import os
import signal
import sys
from contextlib import suppress
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Timer
from time import monotonic, sleep
from typing import Any
from unittest.mock import patch

from snekql.testing.mariadb import temporary_mariadb_server


class _Clock:
    """Freeze only this probe's loop; timer barriers drain earlier deadlines first."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.original = loop.time
        self.now: float | None = None
        self.origin = 0.0

    def time(self) -> float:
        return self.original() if self.now is None else self.now

    def freeze(self) -> None:
        self.origin = self.original()
        self.now = self.origin

    async def advance(self, seconds: float) -> None:
        assert self.now is not None
        self.now += seconds
        barrier = self.loop.create_future()
        handle = self.loop.call_later(0, barrier.set_result, None)
        try:
            await barrier
        finally:
            handle.cancel()

    def elapsed(self) -> float:
        return 0.0 if self.now is None else self.now - self.origin


def _wait_for_file(path: Path, process: asyncio.subprocess.Process) -> None:
    """Real-time/OS handshake, independent of the frozen event-loop clock."""
    deadline = monotonic() + 5
    while not path.exists():
        if process.returncode is not None:
            msg = "child exited before its signal/readiness receipt"
            raise AssertionError(msg)
        if monotonic() >= deadline:
            msg = "child did not publish its signal/readiness receipt"
            raise TimeoutError(msg)
        sleep(0.005)


class _Children:
    """Owned executable stand-ins and observations of their real OS signals."""

    def __init__(self, directory: str, clock: _Clock) -> None:
        self.ready = Path(directory) / "ready"
        self.term = Path(directory) / "term"
        self.clock = clock
        self.processes: list[asyncio.subprocess.Process] = []
        self.server: asyncio.subprocess.Process | None = None
        self.kill_times: list[float] = []
        self.original_spawn = asyncio.create_subprocess_exec
        self.original_signal = os.killpg

    async def spawn(self, *args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        script = (
            "import signal, time; from pathlib import Path; "
            f"signal.signal(signal.SIGTERM, lambda *_: Path({str(self.term)!r}).touch()); "
            f"Path({str(self.ready)!r}).touch(); time.sleep(60)"
            if args[0] == "mariadbd"
            else "pass"
        )
        process = await self.original_spawn(sys.executable, "-c", script, **kwargs)
        self.processes.append(process)
        if args[0] == "mariadbd":
            self.server = process
        return process

    def signal(self, pid: int, signum: int) -> None:
        # Observe a real OS operation, not the helper's internal stop functions.
        if (
            self.server is not None
            and pid == self.server.pid
            and signum == signal.SIGKILL
        ):
            self.kill_times.append(self.clock.elapsed())
        self.original_signal(pid, signum)

    def kill(self) -> None:
        for process in tuple(self.processes):
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()

    async def reap(self) -> None:
        self.kill()
        for process in self.processes:
            await process.wait()


async def probe() -> dict[str, Any]:
    """Return outcomes before rescue cleanup, never manufactured waitpid evidence."""
    clock = _Clock(asyncio.get_running_loop())
    watchdog_fired = Event()
    with TemporaryDirectory(prefix="sq-stop-") as directory:
        children = _Children(directory, clock)
        data = Path(directory) / "data"
        (data / "mysql").mkdir(parents=True)

        def rescue() -> None:
            # A missing escalation must fail boundedly, not leave an ignored-TERM child.
            watchdog_fired.set()
            children.kill()

        async def advance_after_term(process: asyncio.subprocess.Process) -> bool:
            await asyncio.to_thread(_wait_for_file, children.term, process)
            await clock.advance(9)
            alive = process.returncode is None and not children.kill_times
            await clock.advance(2)
            return alive

        watchdog = Timer(10, rescue)
        watchdog.start()
        drivers: list[asyncio.Task[bool]] = []
        try:
            with (
                patch("asyncio.create_subprocess_exec", children.spawn),
                patch("os.killpg", children.signal),
                patch.object(clock.loop, "time", clock.time),
            ):
                try:
                    async with temporary_mariadb_server(
                        runtime_base_directory=Path(directory), data_directory=data
                    ):
                        assert children.server is not None
                        await asyncio.to_thread(
                            _wait_for_file, children.ready, children.server
                        )
                        clock.freeze()
                        driver = asyncio.create_task(
                            advance_after_term(children.server)
                        )
                        drivers.append(driver)
                    # Snapshot immediately on public context return, before any
                    # await or fallback can rescue an un-reaped child for the test.
                    report = {
                        "term_received": children.term.exists(),
                        "server_returncode": children.server.returncode,
                        "all_reaped": all(
                            p.returncode is not None for p in children.processes
                        ),
                        "kill_times": list(children.kill_times),
                    }
                    report["alive_at_nine"] = await driver
                finally:
                    clock.now = None
                    for driver in drivers:
                        driver.cancel()
                    await asyncio.gather(*drivers, return_exceptions=True)
        finally:
            # Cleanup is deliberately outside the report's reaping observation.
            try:
                await children.reap()
            finally:
                watchdog.cancel()
                watchdog.join()
        report["watchdog_fired"] = watchdog_fired.is_set()
        return report


if __name__ == "__main__":
    print(dumps(asyncio.run(probe())))
