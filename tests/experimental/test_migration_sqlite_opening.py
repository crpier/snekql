"""Actual Linux-blocked SQLite opening retains ownership after caller expiry."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal

from anyio import TemporaryDirectory
from snektest import Param, assert_eq, assert_not_in, test


@test(
    [
        Param[Literal["deadline", "task", "scope"]](value="deadline", name="deadline"),
        Param[Literal["deadline", "task", "scope"]](value="task", name="task"),
        Param[Literal["deadline", "task", "scope"]](value="scope", name="scope"),
    ],
    mark="slow",
)
async def sqlite_abandoned_opening_reaps_late_connection_before_fresh_role_deployment(  # noqa: PLR0915 - retain the operator lifecycle
    mode: Literal["deadline", "task", "scope"],
) -> None:
    """A deadline is not physical stop; explicit late close must not rely on GC."""
    fixtures = Path(__file__).parent / "fixtures"
    flags = ["-X", "lazy_imports=all"] if sys.get_lazy_imports() == "all" else []
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
    async with TemporaryDirectory() as directory:
        path = Path(directory) / "app.db"
        lease = await asyncio.create_subprocess_exec(
            sys.executable,
            *flags,
            str(fixtures / "sqlite-opening" / "lease.py.in"),
            str(path),
            sys.get_lazy_imports(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        operator: asyncio.subprocess.Process | None = None
        try:
            assert lease.stdout is not None
            assert_eq(await asyncio.wait_for(lease.stdout.readline(), 3), b"held\n")
            operator = await asyncio.create_subprocess_exec(
                sys.executable,
                *flags,
                "-Walways::ResourceWarning",
                str(fixtures / "sqlite-opening" / "operator.py.in"),
                str(path),
                str(fixtures / "role-interruption" / "sqlite"),
                sys.get_lazy_imports(),
                mode,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            assert operator.stdout is not None
            assert_eq(await asyncio.wait_for(lease.stdout.readline(), 3), b"breaking\n")
            if mode != "deadline":
                # Deliberately exceed the checked-out I/O budget before cancelling.
                await asyncio.sleep(0.05)
                assert operator.stdin is not None
                operator.stdin.write(b"cancel\n")
                await operator.stdin.drain()
            # No outer cancellation serves as the library deadline action.
            receiving = asyncio.create_task(operator.stdout.readline())
            done, _ = await asyncio.wait({receiving}, timeout=1)
            if not done:
                receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
            assert_eq(
                bool(done), True, msg="SQLite opening acquisition deadline ignored"
            )
            record = json.loads(receiving.result())
            assert_eq(record["outcome"], mode)
            assert_eq(record["yielded"], False)
            if mode == "deadline":
                assert "opening migration connection" in record["message"]
            elif mode == "task":
                assert_eq(record["message"], "CancelledError")
            else:
                assert_eq(record["message"], "caller scope caught cancellation")
            tids = record["waiters"]
            assert tids, "deadline must not be mistaken for physical open stop"
            for tid in tids:
                channel = Path(f"/proc/{operator.pid}/task/{tid}/wchan")
                assert (await asyncio.to_thread(channel.read_text)).endswith(
                    "break_lease"
                )
            assert lease.stdin is not None and operator.stdin is not None
            lease.stdin.close()
            _, lease_error = await asyncio.wait_for(lease.communicate(), 3)
            assert_eq((lease.returncode, lease_error), (0, b""))
            operator.stdin.write(b"released\n" + json.dumps(tids).encode() + b"\n")
            await operator.stdin.drain()
            operator.stdin.close()
            stdout, stderr = await asyncio.wait_for(operator.communicate(), 10)
            assert_eq(operator.returncode, 0, msg=stderr.decode())
            assert_not_in(
                b"ResourceWarning",
                stderr,
                msg="late open relied on implicit GC close: " + stderr.decode(),
            )
            disposed, deployed = [json.loads(line) for line in stdout.splitlines()]
            assert_eq(disposed["disposed"], True)
            assert_eq(disposed["database_descriptors"], [])
            assert_eq(deployed["rows"], [[1, "admin"], [2, "user"], [3, "user"]])
            assert_eq(deployed["originals_unchanged"], True)
        finally:
            # Closing the helper's stdin releases our lease even on a RED.
            await _stop(lease)
            await _stop(operator)


async def _stop(process: asyncio.subprocess.Process | None) -> None:
    """Reap only this test's processes, releasing their stdin-owned resources."""
    if process is None:
        return
    if process.stdin is not None:
        process.stdin.close()
    try:
        await asyncio.wait_for(process.wait(), 3)
    except TimeoutError:
        process.kill()
        await process.wait()
