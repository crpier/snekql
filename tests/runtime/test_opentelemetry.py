"""Optional integration through public SDK readers and runtime observers."""

import sys
from asyncio import CancelledError
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from anyio import run_process
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, get_current_span
from snektest import Param, assert_eq, assert_raises, fixture, load_fixture, test

from snekql import sqlite
from snekql.model import BackendFamily
from snekql.opentelemetry import OpenTelemetryObserver
from tests.runtime.test_raw_execution import provide_raw_case


@dataclass
class Exporters:
    metrics: InMemoryMetricReader
    meters: MeterProvider
    spans: InMemorySpanExporter
    tracers: TracerProvider


@fixture
def provide_exporters() -> Generator[Exporters]:
    metrics = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[metrics], shutdown_on_exit=False)
    spans = InMemorySpanExporter()
    tracers = TracerProvider(shutdown_on_exit=False)
    tracers.add_span_processor(SimpleSpanProcessor(spans))
    try:
        yield Exporters(metrics, meters, spans, tracers)
    finally:
        meters.shutdown()
        tracers.shutdown()


@test(mark="medium")
async def durations_reach_sdk_reader() -> None:
    """The optional observer records all six runtime measurement kinds."""
    exporters = load_fixture(provide_exporters())
    observer = OpenTelemetryObserver(meter=exporters.meters.get_meter("test"))
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database,
        database.transaction() as transaction,
        transaction.fetch_chunks(sqlite.raw("SELECT 1 AS number"), size=1) as stream,
    ):
        await anext(stream)
    metrics = exporters.metrics.get_metrics_data()
    assert metrics is not None
    recorded = [
        metric
        for resource in metrics.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    ]
    assert_eq([metric.name for metric in recorded], ["snekql.operation.duration"])
    assert_eq(
        {
            point.attributes["snekql.kind"]
            for point in recorded[0].data.data_points
            if point.attributes
        },
        {
            "pool_wait",
            "pool_checkout",
            "driver",
            "materialization",
            "transaction",
            "stream",
        },
    )


@test(mark="medium")
async def metric_fingerprints_require_allowlist() -> None:
    """Changing SQL shapes cannot create unbounded metric label values."""
    exporters = load_fixture(provide_exporters())
    known = sqlite.CompiledQuery(
        backend="sqlite", sql="SELECT ?", params=()
    ).fingerprint
    observer = OpenTelemetryObserver(
        meter=exporters.meters.get_meter("test"), fingerprints=frozenset({known})
    )
    for index, fingerprint in enumerate(
        (known, "v1:" + "a" * 64, "v1:" + "b" * 64, "raw", None)
    ):
        observer(
            sqlite.TelemetryEvent(
                backend="sqlite",
                duration_seconds=0.25,
                fingerprint=fingerprint,
                kind="driver",
                occurred_at_ns=2_000_000_000,
                operation_id=index,
                outcome="success",
                phase="finish",
            )
        )
    metrics = exporters.metrics.get_metrics_data()
    assert metrics is not None
    labels = {
        point.attributes["snekql.query.fingerprint"]
        for resource in metrics.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
        if point.attributes
    }
    assert_eq(labels, {known, "other", "raw", "none"})


@test(mark="medium")
async def spans_preserve_request_parent() -> None:
    """Runtime spans use the request parent without becoming caller context."""
    exporters = load_fixture(provide_exporters())
    tracer = exporters.tracers.get_tracer("test")
    observer = OpenTelemetryObserver(tracer=tracer)
    with tracer.start_as_current_span("request") as parent:
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=":memory:"), observer=observer
            ) as database,
            database.transaction() as transaction,
        ):
            await transaction.fetch_one(
                sqlite.raw("SELECT 'private-value' AS private_alias")
            )
            assert_eq(get_current_span().get_span_context(), parent.get_span_context())
    spans = [
        span for span in exporters.spans.get_finished_spans() if span.name != "request"
    ]
    assert spans
    assert all(span.parent == parent.get_span_context() for span in spans)
    assert "private" not in str([span.to_json() for span in spans])


@test(mark="medium")
async def span_capacity_drops_without_stopping_metrics() -> None:
    """A capped observer drops excess spans, records durations, and reuses capacity."""
    exporters = load_fixture(provide_exporters())
    observer = OpenTelemetryObserver(
        tracer=exporters.tracers.get_tracer("test"),
        meter=exporters.meters.get_meter("test"),
        max_active_spans=1,
    )
    for index in (1, 2):
        observer(
            sqlite.TelemetryEvent(
                backend="sqlite",
                duration_seconds=None,
                kind="driver",
                occurred_at_ns=1_000_000_000,
                operation_id=index,
                outcome=None,
                phase="start",
            )
        )
    for index in (1, 2):
        observer(
            sqlite.TelemetryEvent(
                backend="sqlite",
                duration_seconds=0.5,
                kind="driver",
                occurred_at_ns=1_500_000_000,
                operation_id=index,
                outcome="success",
                phase="finish",
            )
        )
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=None,
            kind="stream",
            occurred_at_ns=2_000_000_000,
            operation_id=3,
            outcome=None,
            phase="start",
        )
    )
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=0.5,
            kind="stream",
            occurred_at_ns=2_500_000_000,
            operation_id=3,
            outcome="success",
            phase="finish",
        )
    )
    assert_eq(
        [span.name for span in exporters.spans.get_finished_spans()],
        ["snekql.driver", "snekql.stream"],
    )
    assert_eq(observer.dropped_spans, 1)
    metrics = exporters.metrics.get_metrics_data()
    assert metrics is not None
    points = [
        point
        for resource in metrics.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]
    assert all(isinstance(point, HistogramDataPoint) for point in points)
    assert_eq(
        sum(point.count for point in points if isinstance(point, HistogramDataPoint)), 3
    )


@test(
    [
        Param[dict[str, Any]](value=options, name=str(index))
        for index, options in enumerate(
            (
                {},
                {"max_active_spans": 0},
                {"max_active_spans": True},
                {"fingerprints": {"v1:" + "a" * 64}},
                {"fingerprints": frozenset({"not-a-fingerprint"})},
                {
                    "fingerprints": frozenset(
                        f"v1:{index:064x}" for index in range(1025)
                    )
                },
            )
        )
    ],
    mark="medium",
)
async def invalid_configuration_rejected(options: dict[str, Any]) -> None:
    """Reject silent no-op configuration and unbounded or malformed label inputs."""
    exporters = load_fixture(provide_exporters())
    with assert_raises(sqlite.ModelValidationError):
        if options:
            OpenTelemetryObserver(meter=exporters.meters.get_meter("test"), **options)
        else:
            OpenTelemetryObserver()


@test(
    [
        Param[BackendFamily]("sqlite", name="sqlite"),
        Param[BackendFamily]("mariadb", name="mariadb"),
    ],
    [Param("failure", name="failure"), Param("cancellation", name="cancellation")],
    mark="slow",
)
async def terminal_spans_keep_parent_without_exception_data(
    backend: BackendFamily, failure: str
) -> None:
    """Failed and cancelled streams retain request ancestry and omit exception data."""
    exporters = load_fixture(provide_exporters())
    tracer = exporters.tracers.get_tracer("test")
    observer = OpenTelemetryObserver(tracer=tracer)
    case = await load_fixture(provide_raw_case(backend, observer=observer))
    with (
        tracer.start_as_current_span("request") as parent,
        assert_raises(
            CancelledError if failure == "cancellation" else sqlite.ModelValidationError
        ),
    ):
        async with case.database.transaction() as transaction:
            async with transaction.fetch_chunks(
                case.namespace.raw("SELECT 'secret-input' AS value"), size=1
            ) as stream:
                await anext(stream)
                message = "secret-error"
                if failure == "cancellation":
                    raise CancelledError(message)
                raise sqlite.ModelValidationError(message)
    terminal = [
        span
        for span in exporters.spans.get_finished_spans()
        if span.name in ("snekql.stream", "snekql.transaction")
    ]
    assert_eq(len(terminal), 2)
    assert all(
        span.parent == parent.get_span_context()
        and span.status.status_code == StatusCode.ERROR
        for span in terminal
    )
    assert all(not span.events for span in terminal)
    assert "secret" not in str([span.to_json() for span in terminal])


@test(mark="medium")
async def trace_uses_monotonic_duration() -> None:
    """A backwards wall-clock adjustment cannot produce a negative span duration."""
    exporters = load_fixture(provide_exporters())
    observer = OpenTelemetryObserver(tracer=exporters.tracers.get_tracer("test"))
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=None,
            kind="driver",
            occurred_at_ns=2_000_000_000,
            operation_id=1,
            outcome=None,
            phase="start",
        )
    )
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=0.5,
            kind="driver",
            occurred_at_ns=1_000_000_000,
            operation_id=1,
            outcome="success",
            phase="finish",
        )
    )
    (span,) = exporters.spans.get_finished_spans()
    assert_eq((span.start_time, span.end_time), (2_000_000_000, 2_500_000_000))


@test(mark="medium")
async def failed_span_start_releases_capacity() -> None:
    """An SDK start failure cannot exhaust the adapter's bounded span storage."""
    exporters = load_fixture(provide_exporters())
    tracer = exporters.tracers.get_tracer("test")
    observer = OpenTelemetryObserver(tracer=tracer, max_active_spans=1)
    start = sqlite.TelemetryEvent(
        backend="sqlite",
        duration_seconds=None,
        kind="driver",
        occurred_at_ns=1_000_000_000,
        operation_id=1,
        outcome=None,
        phase="start",
    )
    with (
        patch.object(
            type(tracer),
            "start_span",
            side_effect=sqlite.DatabaseRuntimeError("private-sdk-error"),
        ),
        assert_raises(sqlite.DatabaseRuntimeError),
    ):
        observer(start)
    observer(start)
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=0.5,
            kind="driver",
            occurred_at_ns=1_500_000_000,
            operation_id=1,
            outcome="success",
            phase="finish",
        )
    )
    assert_eq(len(exporters.spans.get_finished_spans()), 1)
    assert_eq(observer.dropped_spans, 0)


@test(mark="medium")
async def metric_failure_still_ends_span() -> None:
    """A broken SDK metric instrument cannot retain an otherwise finished span."""
    exporters = load_fixture(provide_exporters())
    meter = exporters.meters.get_meter("test")
    histogram = meter.create_histogram("probe")
    observer = OpenTelemetryObserver(
        tracer=exporters.tracers.get_tracer("test"), meter=meter
    )
    with patch.object(
        type(histogram),
        "record",
        side_effect=sqlite.DatabaseRuntimeError("private-sdk-error"),
    ):
        async with await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database:
            async with database.transaction():
                pass
            failures = database.pool_stats().observer_failures
    assert_eq(failures, 5)
    assert_eq(len(exporters.spans.get_finished_spans()), 5)


@test(mark="slow")
async def backend_imports_do_not_require_opentelemetry() -> None:
    """Applications using ordinary observers do not need the optional API package."""
    script = """
from importlib.abc import MetaPathFinder
import sys
class NoOpenTelemetry(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("opentelemetry"):
            raise ModuleNotFoundError("optional dependency blocked")
sys.meta_path.insert(0, NoOpenTelemetry())
from snekql import sqlite, mariadb
assert sqlite.TelemetryEvent is mariadb.TelemetryEvent
assert not any(name.startswith("opentelemetry") for name in sys.modules)
"""
    completed = await run_process([sys.executable, "-c", script])
    assert_eq(completed.returncode, 0)


@test(mark="medium")
async def histogram_resolves_subsecond_latencies() -> None:
    """Default histogram advice distinguishes database timings below one second."""
    exporters = load_fixture(provide_exporters())
    observer = OpenTelemetryObserver(meter=exporters.meters.get_meter("test"))
    observer(
        sqlite.TelemetryEvent(
            backend="sqlite",
            duration_seconds=0.002,
            kind="driver",
            occurred_at_ns=1_000_000_000,
            operation_id=1,
            outcome="success",
            phase="finish",
        )
    )
    metrics = exporters.metrics.get_metrics_data()
    assert metrics is not None
    points = [
        point
        for resource in metrics.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]
    (point,) = points
    assert isinstance(point, HistogramDataPoint)
    assert_eq(
        point.explicit_bounds,
        (
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
    )
