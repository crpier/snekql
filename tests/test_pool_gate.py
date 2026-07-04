"""FIFO pool-admission gate fairness and cancellation tests.

``FairAdmissionGate`` owns the ticket-queue admission algorithm shared by the
backend connection pools. These tests exercise the gate directly, without any
database: capacity limits, strict FIFO service order, deadline handling, and
cancellation-safe cleanup of parked waiters.
"""

from __future__ import annotations

from collections.abc import Callable

import anyio
from snektest import assert_eq, assert_raises, test

from snekql._pool_gate import FairAdmissionGate
from snekql.errors import DatabaseClosingError, PoolTimeoutError

_TIMEOUT = 30.0


def _accept_all_work() -> None:
    """Accept all work; stand-in for a pool's ``check_accepting_work``."""

    return


def _make_gate(
    capacity: int,
    check_accepting_work: Callable[[], None] = _accept_all_work,
) -> FairAdmissionGate:
    """Build a gate with an accept-everything work check by default."""

    return FairAdmissionGate(
        capacity=capacity,
        check_accepting_work=check_accepting_work,
        log_label="test",
    )


async def _admit(
    gate: FairAdmissionGate,
    acquisition_timeout: float = _TIMEOUT,
) -> None:
    """Admit through the gate with a deadline derived from the timeout."""

    await gate.admit(
        anyio.current_time() + acquisition_timeout,
        acquisition_timeout,
    )


@test(mark="medium")
async def admits_up_to_capacity_then_parks_the_next_acquirer() -> None:
    """The gate admits ``capacity`` acquirers at once; the next one parks."""

    gate = _make_gate(2)
    served: list[str] = []

    await _admit(gate)
    await _admit(gate)
    assert_eq(gate.admitted, 2)

    async def third() -> None:
        await _admit(gate)
        served.append("third")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(third)
        await anyio.wait_all_tasks_blocked()
        assert_eq(served, [])

        await gate.release()

    assert_eq(served, ["third"])
    assert_eq(gate.admitted, 2)


@test(mark="medium")
async def releasing_task_does_not_barge_past_a_parked_waiter() -> None:
    """Re-admitting after release must queue behind an already-parked waiter."""

    gate = _make_gate(1)
    events: list[str] = []

    await _admit(gate)

    async def waiter() -> None:
        await _admit(gate)
        events.append("waiter-admitted")
        await gate.release()
        events.append("waiter-released")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(waiter)
        await anyio.wait_all_tasks_blocked()

        await gate.release()
        events.append("readmit-start")
        await _admit(gate)
        events.append("readmit-done")
        await gate.release()

    assert_eq(
        events,
        [
            "readmit-start",
            "waiter-admitted",
            "waiter-released",
            "readmit-done",
        ],
    )


@test(mark="medium")
async def parked_waiters_are_admitted_in_strict_arrival_order() -> None:
    """Multiple parked waiters pass the gate FIFO, not LIFO."""

    gate = _make_gate(1)
    order: list[str] = []

    await _admit(gate)

    async def waiter(name: str) -> None:
        await _admit(gate)
        order.append(name)
        await gate.release()

    async with anyio.create_task_group() as task_group:
        for name in ("first", "second", "third"):
            task_group.start_soon(waiter, name)
            await anyio.wait_all_tasks_blocked()
        await gate.release()

    assert_eq(order, ["first", "second", "third"])


@test(mark="medium")
async def admit_past_deadline_raises_and_discards_the_ticket() -> None:
    """A waiter that times out leaves the queue so later waiters get served."""

    gate = _make_gate(1)
    served: list[str] = []
    timed_out = anyio.Event()

    await _admit(gate)

    async def impatient_waiter() -> None:
        with assert_raises(PoolTimeoutError):
            await _admit(gate, acquisition_timeout=0.05)
        timed_out.set()

    async def patient_waiter() -> None:
        await _admit(gate)
        served.append("patient")
        await gate.release()

    async with anyio.create_task_group() as task_group:
        # First in line; it will time out while parked.
        task_group.start_soon(impatient_waiter)
        await anyio.wait_all_tasks_blocked()
        # Second in line, queued strictly behind the impatient one.
        task_group.start_soon(patient_waiter)
        await anyio.wait_all_tasks_blocked()

        await timed_out.wait()
        await gate.release()

    assert_eq(served, ["patient"])


@test(mark="medium")
async def admit_with_expired_deadline_at_capacity_raises_immediately() -> None:
    """A zero/expired timeout at capacity fails fast without parking."""

    gate = _make_gate(1)

    await _admit(gate)

    with assert_raises(PoolTimeoutError):
        await gate.admit(anyio.current_time(), 0.0)

    # The failed acquirer left no dead ticket behind: after a release, a fresh
    # acquirer is admitted instead of parking behind a phantom waiter.
    await gate.release()
    await _admit(gate, acquisition_timeout=1.0)
    assert_eq(gate.admitted, 1)


@test(mark="medium")
async def cancelling_a_parked_waiter_frees_its_fifo_slot() -> None:
    """A waiter cancelled while parked must not block later FIFO waiters.

    If the cancelled acquirer left its ticket at the front of the queue, every
    later waiter would be stuck behind a dead ticket and never get served.
    """

    gate = _make_gate(1)
    served: list[str] = []

    await _admit(gate)

    async def cancellable_waiter(scope_holder: list[anyio.CancelScope]) -> None:
        with anyio.CancelScope() as scope:
            scope_holder.append(scope)
            await _admit(gate)
            served.append("cancelled-waiter")
            await gate.release()

    async def waiter() -> None:
        await _admit(gate)
        served.append("waiter")
        await gate.release()

    scope_holder: list[anyio.CancelScope] = []
    async with anyio.create_task_group() as task_group:
        # First in line; it will be cancelled while parked.
        task_group.start_soon(cancellable_waiter, scope_holder)
        await anyio.wait_all_tasks_blocked()
        # Second in line, queued strictly behind the soon-to-be-cancelled one.
        task_group.start_soon(waiter)
        await anyio.wait_all_tasks_blocked()

        scope_holder[0].cancel()
        await anyio.wait_all_tasks_blocked()
        await gate.release()

    assert_eq(served, ["waiter"])


@test(mark="medium")
async def work_check_error_while_parked_propagates_and_discards_ticket() -> None:
    """A rejected parked waiter re-raises and leaves no dead ticket behind."""

    rejecting = [False]

    def check_accepting_work() -> None:
        if rejecting[0]:
            msg = "database is closing"
            raise DatabaseClosingError(msg)

    gate = _make_gate(1, check_accepting_work)
    rejected = anyio.Event()

    await _admit(gate)

    async def parked_waiter() -> None:
        with assert_raises(DatabaseClosingError):
            await _admit(gate)
        rejected.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(parked_waiter)
        await anyio.wait_all_tasks_blocked()

        rejecting[0] = True
        async with gate.condition:
            gate.condition.notify_all()
        await rejected.wait()

    # The rejected acquirer left no dead ticket behind: once the gate accepts
    # work again, a fresh acquirer is admitted instead of parking forever.
    rejecting[0] = False
    await gate.release()
    await _admit(gate, acquisition_timeout=1.0)
    assert_eq(gate.admitted, 1)


@test(mark="medium")
async def release_completes_under_cancellation() -> None:
    """A shielded release frees the slot and wakes a parked waiter."""

    gate = _make_gate(1)
    served: list[str] = []

    await _admit(gate)

    async def waiter() -> None:
        await _admit(gate)
        served.append("waiter")
        await gate.release()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(waiter)
        await anyio.wait_all_tasks_blocked()

        with anyio.CancelScope() as scope:
            scope.cancel()
            await gate.release()

    assert_eq(served, ["waiter"])
    assert_eq(gate.admitted, 0)
