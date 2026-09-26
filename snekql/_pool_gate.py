"""Internal FIFO admission gate shared by backend connection pools.

Neither backend's underlying checkout is fair on its own, so each connection
pool puts a ``FairAdmissionGate`` in front of it: at most ``capacity``
acquirers are admitted at once, and parked acquirers are served strictly in
arrival order. Pools must uphold two contracts for the gate to decide service
order alone:

- ``capacity`` equals the pool's maximum number of connections, so an admitted
  acquirer always finds a free connection and the post-admission checkout
  never blocks.
- On release, the connection is returned to backend storage *before*
  ``release()`` frees the admission slot, under a cancellation shield, so the
  next FIFO waiter always finds a free connection to check out.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import Literal

import anyio
from anyio.lowlevel import checkpoint

from snekql._observation import Telemetry
from snekql.errors import PoolTimeoutError
from snekql.telemetry import PoolStats
from snekql.validation import NonNegativeFloat, PositiveInt

logger = logging.getLogger(__name__)


class FairAdmissionGate:
    """FIFO ticket-queue admission gate bounding concurrent pool checkouts.

    ``admitted`` counts acquirers that hold an admission slot (a checked-out
    or about-to-be-checked-out connection) and is bounded by ``capacity``.
    ``condition`` is public so pools can piggyback closing bookkeeping on the
    gate's lock and wake parked acquirers to re-run the work check.
    """

    admitted: int
    capacity: PositiveInt

    def __init__(
        self,
        *,
        capacity: PositiveInt,
        check_accepting_work: Callable[[], None],
        log_label: str,
        backend: Literal["sqlite", "mariadb"] = "sqlite",
    ) -> None:
        self.acquisition_cancellations: int = 0
        self.acquisition_failures: int = 0
        self.discarded_connections: int = 0
        self.telemetry: Telemetry = Telemetry(backend)
        self.admitted: int = 0
        self.capacity: PositiveInt = capacity
        # Both drivers run on asyncio. Its Condition restores lock ownership
        # even when Task.cancel() interrupts wake-up, not only cancellation
        # originating from an AnyIO scope.
        self.condition: asyncio.Condition = asyncio.Condition()
        self._check_accepting_work: Callable[[], None] = check_accepting_work
        self._log_label: str = log_label
        # FIFO queue of waiting-acquirer ticket numbers. A parked acquirer may
        # only claim a slot when its ticket is at the front, which stops a task
        # that just released from barging ahead of earlier waiters.
        self._waiters: deque[int] = deque()
        self._next_ticket: int = 0

    def snapshot(self, *, state: Literal["open", "closing", "closed"]) -> PoolStats:
        """Read admission state without yielding or reserving another slot."""
        return PoolStats(
            acquisition_cancellations=self.acquisition_cancellations,
            acquisition_failures=self.acquisition_failures,
            capacity=self.capacity,
            discarded_connections=self.discarded_connections,
            state=state,
            observer_failures=self.telemetry.failures,
            occupied=self.admitted,
            waiters=len(self._waiters),
        )

    async def admit(
        self,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
        /,
    ) -> None:
        """Observe admission while retaining ownership until callbacks return."""
        admitted = False
        try:
            with self.telemetry.measure("pool_wait"):
                await self._admit(deadline, acquisition_timeout)
                admitted = True
        except BaseException:
            if admitted:
                await self.release()
            raise

    async def _admit(
        self,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
        /,
    ) -> None:
        """Take a FIFO admission slot, parking in arrival order under contention.

        Holds ``self.condition`` only while inspecting/claiming the gate; the
        pool's checkout happens after this returns. Raises ``PoolTimeoutError``
        once ``deadline`` passes, and always removes its ticket from the queue
        on any exit while parked.
        """

        ticket: int | None = None
        try:
            while True:
                # Keep admission cancellable even when the asyncio lock is free.
                await checkpoint()
                async with self.condition:
                    self._check_accepting_work()
                    if self._waiter_is_served_first(ticket) and (
                        self.admitted < self.capacity
                    ):
                        if ticket is not None:
                            _ = self._waiters.popleft()
                            ticket = None
                        self.admitted += 1
                        return
                    ticket = self._enqueue_waiter(ticket)
                    await self._wait_for_release(ticket, deadline, acquisition_timeout)
        finally:
            # A notified waiter must acquire the condition again on its next
            # loop iteration. Cancellation there is outside condition.wait(),
            # but still owns a queued ticket that must never block successors.
            if ticket is not None:
                with anyio.CancelScope(shield=True):
                    async with self.condition:
                        self._discard_waiter(ticket)

    async def release(self) -> None:
        """Free an admission slot and wake the next FIFO waiter.

        Shielded because it runs on cleanup paths (acquisition failure and
        release): dropping the slot must complete even under cancellation, or a
        parked FIFO waiter stalls until its own deadline.
        """

        with anyio.CancelScope(shield=True):
            async with self.condition:
                self.admitted -= 1
                self.condition.notify_all()

    def _waiter_is_served_first(self, ticket: int | None) -> bool:
        """Return whether this acquirer may claim a slot now.

        A fresh acquirer (no ticket yet) may proceed only when nobody is queued
        ahead of it; a parked acquirer may proceed only at the front of the
        queue. Must be called while holding ``self.condition``.
        """

        if ticket is None:
            return not self._waiters
        return bool(self._waiters) and self._waiters[0] == ticket

    def _enqueue_waiter(self, ticket: int | None) -> int:
        """Append a new FIFO ticket for a parking acquirer, or reuse its own.

        Must be called while holding ``self.condition``.
        """

        if ticket is not None:
            return ticket
        ticket = self._next_ticket
        self._next_ticket += 1
        self._waiters.append(ticket)
        return ticket

    async def _wait_for_release(
        self,
        ticket: int,
        deadline: float,
        acquisition_timeout: NonNegativeFloat,
    ) -> None:
        """Wait for a slot to free up, or time out the acquisition.

        Must be called while holding ``self.condition``; drops ``ticket`` and
        raises ``PoolTimeoutError`` when the deadline passes.
        """

        remaining_timeout = deadline - anyio.current_time()
        if remaining_timeout > 0:
            try:
                with anyio.fail_after(remaining_timeout):
                    await self.condition.wait()
            except TimeoutError as error:
                self._discard_waiter(ticket)
                logger.warning(
                    "%s connection acquisition timed out (timeout=%s)",
                    self._log_label,
                    acquisition_timeout,
                )
                msg = "timed out acquiring database connection"
                raise PoolTimeoutError(msg) from error
            except BaseException:
                # Cancelled while parked: drop our ticket so later FIFO waiters
                # are not blocked behind a dead acquirer. ``condition.wait`` has
                # re-acquired the lock by the time it propagates, so this runs
                # safely under cancellation.
                self._discard_waiter(ticket)
                raise
            return
        self._discard_waiter(ticket)
        logger.warning(
            "%s connection acquisition timed out (timeout=%s)",
            self._log_label,
            acquisition_timeout,
        )
        msg = "timed out acquiring database connection"
        raise PoolTimeoutError(msg)

    def _discard_waiter(self, ticket: int) -> None:
        """Drop a no-longer-waiting ticket and let the next waiter retry.

        Must be called while holding ``self.condition``.
        """

        if ticket in self._waiters:
            self._waiters.remove(ticket)
        self.condition.notify_all()


__all__ = ["FairAdmissionGate"]
