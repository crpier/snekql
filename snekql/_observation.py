"""Callback dispatch and clocks isolated from query diagnostics."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import copy_context
from inspect import isasyncgenfunction, isawaitable, iscoroutine, iscoroutinefunction
from itertools import count
from time import monotonic_ns, time_ns
from typing import Literal

from anyio import get_cancelled_exc_class

from snekql.errors import DatabaseRuntimeError
from snekql.telemetry import Observer, TelemetryEvent, _EventKind

_OPERATION_IDS = count(1)
"""Process-local correlation IDs, never metric labels or trace IDs."""


def validate_observer(observer: Observer | None) -> None:
    """Reject asynchronous observers before opening database resources."""
    if observer is not None and (
        not callable(observer)
        or iscoroutinefunction(observer)
        or isasyncgenfunction(observer)
        or isasyncgenfunction(getattr(observer, "__call__", None))  # noqa: B004 - inspect async callable instances
        or iscoroutinefunction(getattr(observer, "__call__", None))  # noqa: B004 - inspect async callable instances
    ):
        msg = "observer must be a synchronous callable returning None"
        raise DatabaseRuntimeError(msg)


class Telemetry:
    """Own callback dispatch and timing without changing operation failure policy."""

    def __init__(self, backend: Literal["sqlite", "mariadb"]) -> None:
        self.backend: Literal["sqlite", "mariadb"] = backend
        self.observer: Observer | None = None
        self.failures: int = 0
        self._dispatching: bool = False

    @contextmanager
    def measure(
        self,
        kind: _EventKind,
        *,
        fingerprint: str | None = None,
        succeeded: Callable[[], bool] | None = None,
    ) -> Iterator[None]:
        """Emit in the caller's context; disabled telemetry reads no clocks.

        Finish callback failures cannot replace a pending database failure or
        cancellation. On success, process-control exceptions still propagate;
        callers retain ownership of resources until this context exits.
        """
        observer = self.observer
        if observer is None or self._dispatching:
            yield
            return
        operation_id = next(_OPERATION_IDS)
        started = monotonic_ns()
        outcome: Literal["success", "error", "cancelled"] = "success"
        pending = False
        try:
            self._emit(
                observer,
                TelemetryEvent(
                    backend=self.backend,
                    kind=kind,
                    fingerprint=fingerprint,
                    operation_id=operation_id,
                    phase="start",
                    outcome=None,
                    duration_seconds=None,
                    occurred_at_ns=time_ns(),
                ),
            )
            yield
        except BaseException as error:
            pending = True
            outcome = (
                "cancelled" if isinstance(error, get_cancelled_exc_class()) else "error"
            )
            raise
        finally:
            if outcome == "success" and succeeded is not None and not succeeded():
                outcome = "error"
            event = TelemetryEvent(
                backend=self.backend,
                kind=kind,
                fingerprint=fingerprint,
                operation_id=operation_id,
                phase="finish",
                outcome=outcome,
                duration_seconds=(monotonic_ns() - started) / 1_000_000_000,
                occurred_at_ns=time_ns(),
            )
            try:
                self._emit(observer, event)
            except BaseException:
                if not pending:
                    raise

    def _emit(self, observer: Observer, event: TelemetryEvent) -> None:
        """Never log callback exception text or await an accidental coroutine."""
        self._dispatching = True
        try:
            returned = copy_context().run(observer, event)
            if isawaitable(returned):
                if iscoroutine(returned):
                    returned.close()
                self.failures += 1
            elif returned is not None:
                self.failures += 1
        except Exception:
            self.failures += 1
        finally:
            self._dispatching = False
