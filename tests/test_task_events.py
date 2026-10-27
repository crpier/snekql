"""Test orchestration observes setup failures without hiding them behind watchdogs."""

import asyncio

import anyio
from snektest import Param, assert_eq, assert_is, assert_raises, assert_true, test

from tests.helpers import wait_for_task_event


@test(mark="fast")
async def setup_failure_is_reported_before_readiness_timeout() -> None:
    """An immediate task failure is preserved instead of becoming a readiness timeout."""

    failure = RuntimeError("controlled setup failure")

    async def setup() -> None:
        raise failure

    task = asyncio.create_task(setup())
    try:
        with assert_raises(RuntimeError) as error:
            # This outer watchdog bounds a broken helper, not the startup budget.
            async with asyncio.timeout(1):
                await wait_for_task_event(task, asyncio.Event(), timeout=60)
        assert_is(error.exception, failure)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@test(mark="fast")
async def task_completion_without_readiness_is_a_failure() -> None:
    """Successful early task exit cannot masquerade as reaching the fault gate."""

    async def setup() -> None:
        pass

    task = asyncio.create_task(setup())
    try:
        with assert_raises(AssertionError):
            await wait_for_task_event(task, asyncio.Event(), timeout=60)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@test(mark="fast")
async def readiness_timeout_leaves_setup_task_owned_by_caller() -> None:
    """An expired event budget must not cancel the resource's setup task."""

    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    try:
        with assert_raises(TimeoutError):
            await wait_for_task_event(task, asyncio.Event(), timeout=0)
        release.set()
        assert_is(await task, True)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@test(
    [Param("before", name="already_ready"), Param("during", name="becomes_ready")],
    mark="fast",
)
async def readiness_leaves_setup_task_running(timing: str) -> None:
    """Reaching a fault gate returns control without ending the task under test."""

    ready = asyncio.Event()
    release = asyncio.Event()
    if timing == "before":
        ready.set()

    async def setup() -> str:
        ready.set()
        await release.wait()
        return "setup completed"

    task = asyncio.create_task(setup())
    try:
        async with asyncio.timeout(1):
            await wait_for_task_event(task, ready, timeout=60)
        assert_true(ready.is_set())
        release.set()
        assert_eq(await task, "setup completed")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@test(mark="fast")
async def setup_failure_is_not_hidden_by_simultaneous_readiness() -> None:
    """A reached event cannot hide a task failure already available to the caller."""

    ready = asyncio.Event()
    failure = RuntimeError("failure at the fault gate")

    async def setup() -> None:
        ready.set()
        raise failure

    task = asyncio.create_task(setup())
    try:
        with assert_raises(RuntimeError) as error:
            await wait_for_task_event(task, ready, timeout=60)
        assert_is(error.exception, failure)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@test([Param("native", name="native"), Param("anyio", name="anyio")], mark="fast")
async def cancelling_event_wait_keeps_setup_task_and_releases_owned_waiter(
    mode: str,
) -> None:
    """Cancelling observation does not cancel setup or leave a background event wait."""

    initial_tasks = asyncio.all_tasks()
    release = asyncio.Event()
    waiting = asyncio.Event()
    scope = anyio.CancelScope()
    task = asyncio.create_task(release.wait())

    async def observe() -> None:
        with scope:
            waiting.set()
            await wait_for_task_event(task, asyncio.Event(), timeout=60)
            assert_true(False, msg="observation should be cancelled")

    observer = asyncio.create_task(observe())
    try:
        async with asyncio.timeout(1):
            await waiting.wait()
            if mode == "native":
                observer.cancel("cancel observation only")
                with assert_raises(asyncio.CancelledError):
                    await observer
            else:
                scope.cancel()
                await observer
            release.set()
            assert_is(await task, True)
        assert_eq(asyncio.all_tasks() - initial_tasks, set())
    finally:
        observer.cancel()
        task.cancel()
        await asyncio.gather(observer, task, return_exceptions=True)
