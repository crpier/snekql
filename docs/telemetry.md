# Runtime telemetry

Pass a synchronous observer to `Database.initialize`. Both backend namespaces
export `Observer`, `TelemetryEvent`, and `PoolStats`. The same types are available
from `snekql.telemetry`; no OpenTelemetry dependency is needed.

```python
from snekql import sqlite


async def inspect_pool() -> sqlite.PoolStats:
    events: list[sqlite.TelemetryEvent] = []
    async with await sqlite.Database.initialize(
        sqlite.Config(database=":memory:"),
        observer=events.append,
    ) as database:
        async with database.transaction():
            snapshot = database.pool_stats()
    return snapshot
```

This example retains events for local inspection. Production observers should
record measurements or enqueue events into a bounded processor, not accumulate
an unbounded list.

## Pool snapshots

`database.pool_stats()` reads local state without I/O or acquiring a connection.
Call it on the Database's event loop. It returns a frozen, slotted snapshot;
previous snapshots do not change when transactions finish. Snapshots remain
available after the Database closes and work without an observer.

| Field | Meaning |
| --- | --- |
| `capacity` | Configured admission limit. Exact SQLite `:memory:` databases have capacity one. |
| `occupied` | Reserved admission slots, including checkout/setup, application leases, and detached SQLite cleanup that still owns a slot. |
| `waiters` | Acquirers currently queued for admission. |
| `state` | `open`, `closing`, or `closed`. Closing can also mean failed cleanup has quarantined the pool. |
| `acquisition_failures` | Unsuccessful pool acquisition attempts, excluding cancellation. |
| `acquisition_cancellations` | Acquisition attempts interrupted by cancellation. |
| `discarded_connections` | Explicitly discarded unsafe leases, plus MariaDB connections rejected by checkout probes or session setup. |
| `observer_failures` | Ordinary callback exceptions and invalid non-None callback returns. |

Counters accumulate for the lifetime of this Database. Acquisition counters
settle when an attempt returns or raises, after its observer callbacks complete.
Failures rejected before pool acquisition, such as reusing a Transaction, are not
acquisition failures. A successful checkout followed by failed BEGIN is also not
an acquisition failure; its unsafe connection can still count as discarded.

`occupied / capacity` measures admission utilization, not the number of open
sockets or worker threads. Free slots do not guarantee successful acquisition.
In particular, a closing pool rejects work even if `occupied` is zero. Failed
physical cleanup may retain handles outside the admission count while keeping
the pool quarantined.

Discard counts exclude normal shutdown, healthy age/idle recycling, partial
connection establishment failures, and driver-internal removals snekql cannot
observe. They are not a count of every physical connection close.

## Measurements

Current event kinds are:

- `pool_wait`: FIFO admission, including uncontended admission and timed-out or
  cancelled waits.
- `pool_checkout`: work after admission, including SQLite lazy opening and
  MariaDB replacement, health checks, and session setup. It excludes BEGIN.
- `driver`: native query work and transaction/savepoint control. A buffered
  query includes execution, fetching, and cursor completion in one measurement.
  Streaming measures cursor opening, individual fetches, and cursor cleanup.
  Nested raw cursor completion is not counted twice.
- `materialization`: cardinality checks, result-shape checks, decoding, validation,
  and result packaging. Streaming emits measurements for batches and raw metadata
  checks. EXPLAIN result packaging is included. This is elapsed time, including
  cooperative checkpoints, not a CPU-time measurement.
- `transaction`: from a successful pool checkout, before BEGIN, through terminal
  commit/rollback and lease return or discard scheduling. It excludes acquisition
  and includes application work. Detached physical SQLite close can continue
  afterward while retaining pool capacity.
- `stream`: from the validated stream open attempt through context exit and
  cursor cleanup. It includes caller pauses and early breaks. Exhausting a raw
  cursor can close it before context exit, but the stream still holds the
  transaction lock until exit.

A wait that fails does not emit checkout events. Each attempted measurement
emits a `start` and `finish` event, including failures and cancellation. An
observer may fail to record either event; process termination cannot guarantee
delivery. Bootstrap connection work before initialization returns is not sent
to the observer. Subsequent acquisitions for migrations and schema verification
use the same pool instrumentation. Their internal SQL is not instrumented as
Query Runtime driver work. Pure query compilation and connection-lock waiting
are not driver measurements.

Events contain:

- `backend`, either `sqlite` or `mariadb`.
- `kind` and `phase`.
- `fingerprint`, the query identifier described below, or None for pool,
  transaction, and transaction-control measurements.
- `operation_id`, a process-local correlation ID shared by the start and finish.
  IDs are distinct across Database instances but are not distributed trace IDs.
- `occurred_at_ns`, Unix time in nanoseconds for trace timestamps.
- `duration_seconds`, a monotonic elapsed duration on finish, otherwise None.
- `outcome`, `success`, `error`, or `cancelled` on finish, otherwise None.

Neither timestamps nor durations promise clock precision beyond the host clock.
Elapsed durations never subtract wall-clock timestamps. Do not use operation IDs
or timestamps as metric labels. The backend/kind/outcome labels have bounded values.

A transaction that discards unsafe work without committing reports `error`, even
if the application caught the statement exception. A stream that encountered a
failed batch also reports `error` if the caller caught it. A transaction can still
commit after a handled validation error; its transaction outcome is then
`success`, while the materialization or stream event retains the failure.

Telemetry outcomes do not establish Commit Outcome or retry eligibility. An
acknowledged commit followed by failed cleanup can produce a failed transaction
event. A callback interruption after commit does not erase
`transaction.commit_outcome`. Use that existing evidence and the failure policy
when deciding whether to reconcile or retry.

## Query fingerprints

`query.compile().fingerprint` returns the same identifier carried by builder
query measurements. The v1 identifier is `v1:` followed by the SHA-256 digest of
the backend name, a NUL separator, and exact parameterized SQL encoded as UTF-8.
It never reads or formats `CompiledQuery.params`. It retains no SQL cache.

Different bound values share a fingerprint when their SQL is identical. Backend,
SQL spelling, identifiers, placeholder count, and compiler changes can change
it. It is not a semantic-equivalence test or a persistent query identifier
across compiler versions. SQL-shape variation, such as different IN-list lengths,
can still produce arbitrarily many identifiers.

Raw statements and EXPLAIN use the fixed identifier `raw`; their SQL is not
hashed or exported. Driver control calls, such as COMMIT, have no fingerprint.
Empty builder writes emit no driver event, but can still emit result packaging
with the backend's empty-SQL fingerprint.

Hashing is not encryption for values embedded directly into custom SQL. Do not
embed secrets into custom SQL and assume a digest protects them against guessing.
Bound values are excluded completely. Keep fingerprints out of metric labels
unless using a fixed allowlist and an overflow category. Trace consumers may
record the full fingerprint, subject to their own storage limits.

## Callback policy

Observers run synchronously in an isolated copy of the invoking task's current
context. They can read request ContextVars; changes they make to those bindings
do not leak into application execution. This is not a sandbox for arbitrary
application side effects.

Callbacks must return None and must not block, perform I/O, or re-enter database
work. Async functions, async callable instances, async generators, and
non-callables are rejected before initialization opens resources. A synchronous
wrapper that returns a coroutine is counted as a callback failure; the coroutine
is closed without running it. Other invalid returns are ignored and counted.

Ordinary exceptions never fail the database operation. Their text and tracebacks
are not logged. Inspect `observer_failures` and test the observer independently.
Process-control exceptions, including cancellation, propagate when no database
failure is already pending. Cleanup retains ownership of admission slots and
connections. A finish callback cannot replace a pending database exception or
cancellation.

Disabled observation creates no events and reads no telemetry clocks. Enabled
observation costs two synchronous callbacks per measurement, event allocation,
context copying, and clock reads. The duration includes start-callback overhead
but excludes the finish callback. Callback time can consume an acquisition's
existing deadline; instrumentation does not grant a fresh budget or preempt a
blocking callback.

Events contain no SQL, bound values, connection endpoints, database paths,
credentials, or exception objects. This policy does not change when
`parameter_visibility="values"`. Application observers still have access to
application context; existing exception chains, traceback locals, and external
driver instrumentation are not sanitized by these events.

## Optional OpenTelemetry adapter

Install `snekql[opentelemetry]` for the OpenTelemetry API dependency. Applications
choose and install their SDK and exporters separately. Import the adapter from
`snekql.opentelemetry`, not the backend namespaces.

```python
from opentelemetry.metrics import get_meter
from opentelemetry.trace import get_tracer
from snekql import sqlite
from snekql.opentelemetry import OpenTelemetryObserver


async def read_number() -> object:
    observer = OpenTelemetryObserver(
        meter=get_meter("application"),
        tracer=get_tracer("application"),
        fingerprints=frozenset(),
        max_active_spans=1024,
    )
    async with (
        await sqlite.Database.initialize(
            sqlite.Config(database=":memory:"), observer=observer
        ) as database,
        database.transaction() as transaction,
    ):
        return await transaction.fetch_one(sqlite.raw("SELECT 1 AS number"))
```

Configure providers before creating the observer. Without configured providers,
OpenTelemetry's global getters can return non-recording implementations. The
adapter requires a meter, tracer, or both. It does not install global providers,
start workers, choose exporters, flush, or shut down caller-owned providers.

### Metrics and cardinality

The meter receives `snekql.operation.duration`, a histogram measured in seconds.
Its count also supplies completed-operation counts. Advisory histogram boundaries
range from 100 microseconds to 60 seconds, with subsecond buckets for database
latencies. Applications can override aggregation through SDK views. Attributes are:

- `db.system.name`: `sqlite` or `mariadb`.
- `snekql.kind`: the six measurement kinds above.
- `snekql.outcome`: `success`, `error`, or `cancelled`.
- `snekql.query.fingerprint`: `none` for measurements without a query, `raw` for
  raw operations, an explicitly allowed fingerprint, or `other`.

`fingerprints` must be a frozenset containing at most 1,024 v1 fingerprints.
Populate it from reviewed `query.compile().fingerprint` values. No dynamic
learning or eviction occurs. The default groups all builder queries as `other`.
Do not vary allowlists per request or add unbounded labels through SDK views.
The bound applies per observer configuration; replacing configurations over
process lifetimes can create additional historical series.

Do not sum durations across kinds. Transaction and stream lifetimes include
work measured separately by the driver and materialization histograms.

### Traces and context

Span names are fixed `snekql.<kind>` names. Driver spans have CLIENT kind; other
spans have INTERNAL kind. Spans carry backend, measurement kind, full query
fingerprint when present, and finish outcome. Failed and cancelled measurements
have ERROR status without exception descriptions or exception events.

Every span inherits the application's current OpenTelemetry parent at its start.
The adapter never activates its own spans. Runtime spans therefore appear as
siblings under the request span rather than building an artificial transaction
hierarchy, and application context remains unchanged. End times use the start
Unix timestamp plus monotonic duration, so wall-clock adjustments do not produce
negative durations.

`max_active_spans` is a positive integer limiting retained in-flight spans,
including reservations while SDK start hooks run. Capacity exhaustion drops new
span starts, increments the read-only `observer.dropped_spans` counter, and still
records finish metrics. The default is 1,024. A completed span frees capacity even
if metric recording fails. Dropped spans are not callback failures. Properly exit
Transaction and stream contexts; abandoned contexts retain bounded tracking slots.
The adapter can be shared across Databases, but its capacity and drop count are
shared too.

### Exporter lifecycle and overhead

Use bounded batch processors and background metric readers for network export.
Do not use synchronous network exporters on the database event loop. SDK methods
and processors run synchronously during callbacks; custom SDK hooks must obey the
same nonblocking policy as ordinary observers. snekql cannot make a blocking
processor safe or enforce its timeout.

SDK exceptions reaching the adapter follow the observer failure policy and count
in `pool_stats().observer_failures`. Failures handled internally by the SDK or
exporter do not reach this counter; monitor their diagnostics separately.
Constructor failures occur before observer attachment. Flush and shut down providers after database work has ended, outside
the event loop or through `await anyio.to_thread.run_sync(provider.shutdown)`.
Application SDK resources, baggage, SDK diagnostics, and independently installed
driver instrumentation are outside snekql's redaction policy.

### Exporting pool snapshots

Pool snapshots are separate from duration events. Sample `database.pool_stats()`
on the Database's event loop, then export those immutable snapshots through your
monitoring integration. Do not call it directly from a background OpenTelemetry
observable-instrument callback. For example, an application-owned async task can
periodically call `meter.create_gauge("application.pool.occupied").set(...)` using
`stats.occupied`. Create the gauge once, keep any pool labels fixed, and stop the
sampling task during application shutdown. Export capacity and cumulative failure,
discard, and observer-failure counters from the same snapshot. These are admission
statistics, not physical connection counts.

Query repr/str also redact bindings by default. Explicit local value inspection
uses `query.inspect(parameter_visibility="values")`; it does not change observer
events or the runtime logging policy. See README query inspection.
