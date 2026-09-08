"""Owned subprocess creation and bounded cancellation-resistant cleanup."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from signal import Signals

import anyio

from snekql.testing.mariadb._types import TemporaryMariaDBServerError

_SHUTDOWN_TIMEOUT = 10.0
"""Grace for termination, followed by the same bounded kill/reap grace."""


def _signal_process(process: asyncio.subprocess.Process, *, kill: bool = False) -> None:
    """Signal the owned session on POSIX, including installer subprocesses."""

    try:
        if os.name == "posix":
            os.killpg(process.pid, Signals.SIGKILL if kill else Signals.SIGTERM)
        elif not kill:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        pass


async def _stop_process(process: asyncio.subprocess.Process, *, capture: bool) -> None:
    """Drain pipes while stopping, escalating after the existing terminate grace."""

    waiter = asyncio.create_task(process.communicate() if capture else process.wait())
    try:
        try:
            if process.returncode is None:
                _signal_process(process)
            await asyncio.wait_for(asyncio.shield(waiter), _SHUTDOWN_TIMEOUT)
        except TimeoutError, OSError:
            _signal_process(process, kill=True)
            await asyncio.wait_for(asyncio.shield(waiter), _SHUTDOWN_TIMEOUT)
    except (TimeoutError, OSError) as error:
        msg = f"failed to stop/reap child process {process.pid} after terminate/kill"
        raise TemporaryMariaDBServerError(msg) from error
    finally:
        if not waiter.done():
            waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


async def _finish_cleanup(
    cleanup: asyncio.Task[None],
    original: BaseException | None,
) -> None:
    """Wait through repeated native cancellation as well as AnyIO scope cancellation."""

    cancelled: asyncio.CancelledError | None = None
    with anyio.CancelScope(shield=True):
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                if cancelled is None:
                    cancelled = error
            except Exception:
                break
    try:
        cleanup.result()
    except BaseException as error:
        primary = original if original is not None else cancelled
        if primary is None:
            raise
        if error is not primary:
            primary.add_note(f"child-process cleanup failed: {error}")
    if original is None and cancelled is not None:
        raise cancelled


@asynccontextmanager
async def owned_process(
    *arguments: str,
    capture: bool = False,
    pipe_stdin: bool = False,
    env: Mapping[str, str] | None = None,
) -> AsyncGenerator[asyncio.subprocess.Process]:
    """Keep ownership even if cancellation interrupts process creation's await."""

    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *arguments,
            env=dict(env) if env is not None else None,
            stdin=asyncio.subprocess.PIPE if pipe_stdin else None,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
    )

    async def cleanup() -> None:
        # Creation must settle before a cancelled caller can release ownership.
        process = await spawn
        await _stop_process(process, capture=capture)

    original: BaseException | None = None
    try:
        yield await asyncio.shield(spawn)
    except BaseException as error:
        original = error
        raise
    finally:
        await _finish_cleanup(asyncio.create_task(cleanup()), original)
