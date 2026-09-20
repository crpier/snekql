"""Optional OpenTelemetry observation; importing backend namespaces needs no SDK."""

from re import fullmatch
from threading import Lock

from opentelemetry.metrics import Histogram, Meter
from opentelemetry.trace import Span, SpanKind, StatusCode, Tracer

from snekql.errors import ModelValidationError
from snekql.telemetry import TelemetryEvent

_MAX_FINGERPRINTS = 1024
"""Maximum caller-approved metric fingerprint labels per observer."""


class OpenTelemetryObserver:
    """Export parameter-free measurements through caller-owned meters and tracers.

    Supply either SDK interface or both. Fingerprint metric labels require an
    explicit fixed allowlist; all others use `other`. Span tracking is bounded.
    The application owns nonblocking processors and provider shutdown.

    ```python
    from opentelemetry.metrics import get_meter
    from snekql.opentelemetry import OpenTelemetryObserver

    observer = OpenTelemetryObserver(meter=get_meter("application"))
    ```
    """

    def __init__(
        self,
        *,
        meter: Meter | None = None,
        tracer: Tracer | None = None,
        fingerprints: frozenset[str] = frozenset(),
        max_active_spans: int = 1024,
    ) -> None:
        if meter is None and tracer is None:
            message = "OpenTelemetryObserver requires a meter or tracer"
            raise ModelValidationError(message)
        if type(max_active_spans) is not int or max_active_spans < 1:
            message = "max_active_spans must be a positive integer"
            raise ModelValidationError(message)
        if (
            not isinstance(fingerprints, frozenset)
            or len(fingerprints) > _MAX_FINGERPRINTS
            or any(
                not isinstance(item, str) or fullmatch(r"v1:[0-9a-f]{64}", item) is None
                for item in fingerprints
            )
        ):
            message = (
                "fingerprints must be a frozenset of at most 1024 v1 query fingerprints"
            )
            raise ModelValidationError(message)
        self._fingerprints: frozenset[str] = frozenset(fingerprints)
        self._tracer: Tracer | None = tracer
        self._spans: dict[int, tuple[Span, int] | None] = {}
        self._lock: Lock = Lock()
        self._max_active_spans: int = max_active_spans
        self._dropped_spans: int = 0
        self._duration: Histogram | None = (
            meter.create_histogram(
                "snekql.operation.duration",
                unit="s",
                explicit_bucket_boundaries_advisory=(
                    0.0001,
                    0.0005,
                    0.001,
                    0.005,
                    0.01,
                    0.05,
                    0.1,
                    0.5,
                    1.0,
                    5.0,
                    10.0,
                    30.0,
                    60.0,
                ),
                description="Elapsed runtime measurement duration, separated by kind.",
            )
            if meter is not None
            else None
        )

    def __call__(self, event: TelemetryEvent) -> None:
        attributes = {"db.system.name": event.backend, "snekql.kind": event.kind}
        if event.phase == "start":
            self._start(event, attributes)
            return
        with self._lock:
            opened = self._spans.pop(event.operation_id, None)
        try:
            if opened is not None:
                opened[0].set_attribute("snekql.outcome", event.outcome or "error")
                if event.outcome != "success":
                    opened[0].set_status(StatusCode.ERROR)
            if self._duration is not None and event.duration_seconds is not None:
                attributes["snekql.outcome"] = event.outcome or "error"
                attributes["snekql.query.fingerprint"] = (
                    "none"
                    if event.fingerprint is None
                    else event.fingerprint
                    if event.fingerprint == "raw"
                    or event.fingerprint in self._fingerprints
                    else "other"
                )
                self._duration.record(event.duration_seconds, attributes=attributes)
        finally:
            if opened is not None:
                span, started = opened
                span.end(
                    end_time=started
                    + round((event.duration_seconds or 0) * 1_000_000_000)
                )

    @property
    def dropped_spans(self) -> int:
        """Number of starts omitted because the active-span capacity was full."""
        with self._lock:
            return self._dropped_spans

    def _start(self, event: TelemetryEvent, attributes: dict[str, str]) -> None:
        """Reserve before invoking SDK code, without holding a lock across processors."""
        if self._tracer is None:
            return
        with self._lock:
            if event.operation_id in self._spans:
                return
            if len(self._spans) >= self._max_active_spans:
                self._dropped_spans += 1
                return
            self._spans[event.operation_id] = None
        try:
            if event.fingerprint is not None:
                attributes["snekql.query.fingerprint"] = event.fingerprint
            span = self._tracer.start_span(
                f"snekql.{event.kind}",
                attributes=attributes,
                kind=SpanKind.CLIENT if event.kind == "driver" else SpanKind.INTERNAL,
                start_time=event.occurred_at_ns,
            )
        except BaseException:
            with self._lock:
                self._spans.pop(event.operation_id, None)
            raise
        with self._lock:
            self._spans[event.operation_id] = (span, event.occurred_at_ns)


__all__ = ["OpenTelemetryObserver"]
