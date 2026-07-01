# snekql benchmarks

Standalone performance benchmarks, kept separate from the `snektest` unit suite.
Two families:

- **Concurrency** (`benchmarks.run`): runtime behavior under concurrent async
  load — pool fairness, event-loop stalls, throughput/latency across pool sizes
  and workload mixes ([issue #66](https://github.com/crpier/snekql/issues/66)).
- **Construction** (`benchmarks.construction`): the pure-CPU cost of the
  immutable Query Builder, with no I/O. See
  [Query construction throughput](#query-construction-throughput) below.

## Running

```bash
# Everything available (SQLite + MariaDB if the binaries are installed)
uv run python -m benchmarks.run

# One backend, longer run, more seeded rows for the point-read/write/mixed
# workloads (`--rows`); the large-select probe is sized separately
# (`--large-select-rows`)
uv run python -m benchmarks.run --backend sqlite --duration 5 --rows 20000 \
    --large-select-rows 50000

# Tune the sweep
uv run python -m benchmarks.run --pool-sizes 1 4 16 --worker-counts 1 8 32
```

MariaDB scenarios spin up a throwaway server via the project's
`TemporaryMariaDBServer` helper; they are skipped (with a message) when the
MariaDB binaries are not installed. No external server or credentials are
needed.

Per-scenario database setup is handled by snektest fixtures
(`benchmarks/_fixtures.py`): a fixture handle doubles as an async context
manager, so the driver consumes it standalone with `async with` — no snektest
runner — while getting connect → migrate → seed setup and deterministic
teardown for free. The benchmarks themselves stay plain scripts (they emit
measurements, not pass/fail verdicts); only the setup half is on fixtures.

## What is measured

Each scenario runs `--workers` async tasks that repeatedly open a transaction
and run one operation for `--duration` seconds, while a 5 ms heartbeat task
records event-loop wake-up lateness. Reported per scenario:

- **throughput** — completed operations per second.
- **latency** — per-operation wall time (transaction acquire + execute), p50 /
  p99 / max in milliseconds. `max` captures starvation.
- **fairness** — Jain's index over per-worker completed-op counts. `1.0` means
  every worker got an equal share; values toward `1/workers` mean one worker
  monopolized the pool. The per-worker `min..max` op spread is printed too.
- **loop stall** — worst heartbeat lateness; a large value means a synchronous
  stretch (typically row materialization) blocked the event loop.

## Findings (baseline captured 2026-06, SQLite + MariaDB on Linux)

### 1. SQLite pool fairness — fixed in this change

Before the fix, the SQLite pool used `condition.notify_all()` with no ordering,
so a task that released a connection could immediately re-acquire it ahead of
tasks already waiting (barging). Under `pool_size=1, workers=8` one worker
completed **2711** operations while another completed **1**, with a **~1 s** max
acquire latency (Jain ≈ 0.13).

The pool now serves waiters first-in-first-out (a ticket queue gates
acquisition). Same workload after the fix: per-worker spread **1167..1168**, max
latency **6 ms**, Jain **1.00**, with throughput unchanged. See
`tests/sqlite/test_pool_fairness.py`.

### 2. MariaDB pool fairness — open follow-up

The MariaDB runtime delegates to the underlying `aiomysql` pool, which exhibits
the same starvation when `workers > pool_size`: `pool=1, workers=32` reached
Jain **0.03** (one worker did 14848 ops, another did 1) with max latency equal
to the whole run. This is inside `aiomysql`, not snekql's own pool, so it needs
a wrapper-level fair queue. Filed as a follow-up.

### 3. `fetch_all` materialization blocks the event loop — fixed in this change

`Transaction.fetch_all` materializes and validates every row synchronously after
`fetchall()`. Before the fix, selecting 20000 rows produced a **57 ms** (SQLite)
/ **115 ms** (MariaDB) event-loop stall — long enough to delay every other task
on the loop.

The materialization loop now awaits an `anyio` checkpoint every
`FETCH_ALL_YIELD_INTERVAL` (1000) rows, capping any single uninterrupted run.
The `large-select` scenario (20000-row `fetch_all`, 4 workers) over the SQLite
backend, before vs after:

| | max loop stall | p99 loop stall | throughput |
|---|---|---|---|
| baseline (`origin/main`) | 63.3 ms | 57.7 ms | 8.0 ops/s |
| cooperative yield | 11.9 ms | 9.2 ms | 8.0 ops/s |

~5x stall reduction with no measurable throughput cost. The driver `fetchall()`
itself is awaited (aiosqlite offloads to a thread, aiomysql awaits the buffered
read), so the synchronous Python-level materialization the checkpoint breaks up
is the stall this targets. `fetch_chunks(...)` still streams server-side and
keeps stalls negligible without buffering the whole result; it remains the
recommended path for large or unbounded reads. Reproduce with
`uv run python -m benchmarks.run --backend sqlite`. See issue #187.

## Pool-size guidance for async services

From the sweep (read-mostly point queries, one event loop):

- **Throughput scales with pool size only up to real parallelism.** SQLite
  serializes writes regardless of pool size; extra connections mainly help
  overlap read latency. MariaDB read throughput plateaus around a small pool
  (≈4–16) because the bottleneck becomes per-query round-trips, not connections.
- **Size the pool to expected concurrent in-flight transactions, not to total
  task count.** A pool far smaller than the worker count still completes all
  work fairly (post-fix), just with higher queueing latency.
- **Practical defaults:** SQLite `pool_size` 4–8 for a typical service (1 is
  fine for write-bound workloads since writes serialize anyway); MariaDB
  `pool_size` 8–16. Until the MariaDB fairness follow-up lands, keep
  `pool_size >= peak concurrent transactions` to avoid `aiomysql`-level
  starvation.
- **`acquire_timeout` is a backpressure control,** not a tuning knob: set it to
  the longest a request may reasonably wait for a connection, so overload
  surfaces as `PoolTimeoutError` instead of unbounded latency.
- **Use `fetch_chunks` for large reads** to avoid event-loop stalls; reserve
  `fetch_all` for bounded result sets.

## Query construction throughput

`benchmarks.construction` measures how fast `select(...).where(...).limit(...)`
chains (and insert/update builds) turn into immutable query state — no database,
no async. It reports a throughput distribution over repeated trials and
per-query retained memory.

```bash
uv run python -m benchmarks.construction
```

Each workload is timed over 15 trials of 50 000 builds (after a 5 000-build
warmup), with the GC disabled inside each timed trial so a background collection
cannot land mid-sample. Reported per workload: median and mean builds/second,
the coefficient of variation (stdev / mean) across trials, and mean retained
bytes per built query (`tracemalloc` snapshot diff with every query held alive).

### Variance

Within-run variance is small (CV typically < 1%). The larger source of noise is
**cross-run drift** from CPU frequency scaling / thermals: back-to-back full runs
of the same code can differ by ~5%, more than the within-run CV. So before/after
comparisons interleave the two builds (A/B/A) on the same machine state rather
than comparing one run to one run; the A runs must bracket the B run for a delta
to be real. Pin a core and disable turbo for the steadiest numbers.

### Finding: concrete-type checks before structural protocol checks

Profiling construction showed two dominant costs: `dataclasses.replace` on every
immutable builder transition, and `isinstance` against the `@runtime_checkable`
`SqlCompilable` / `DialectSelectable` protocols (each such check walks the
operand's attributes via `inspect.getattr_static`). The dialect-expression
protocols are a niche extension point (e.g. MariaDB JSON operators); the
overwhelmingly common operand is a plain `Attr` column, yet the hot construction
paths (`require_selectable`, `selectable_owner_model`,
`ensure_predicate_targets_models`) reached the expensive protocol check before
falling through to the column case.

Testing the concrete `Attr` (and `Aggregate` / `Scalar`) types *before* the
structural protocol check removes that cost for the common path. The reordering
is semantics-preserving: `Attr`/`Aggregate`/`Scalar` are disjoint from the
protocol-only dialect leaves, so every value still selects the same branch (the
full `snektest` suite passes unchanged, and per-query retained memory is
identical — the same state objects are built).

Before (`origin/main`) vs after, median builds/second (interleaved A/B/A, SQLite
models, Linux), with per-query bytes unchanged:

| workload | baseline | optimized | change | bytes/query |
|---|---|---|---|---|
| point_read (`select.where.limit`) | 102,827 | 141,367 | **+37%** | 530 |
| filtered (2×where + order_by + limit/offset) | 40,686 | 65,701 | **+62%** | 803 |
| projection (`select(col,col).where.limit`) | 56,595 | 111,008 | **+97%** | 515 |
| update (`set.where`) | 151,157 | 237,157 | **+57%** | 529 |
| insert (no protocol checks) | 260,119 | 263,160 | +1% (noise) | 441 |

`insert` builds touch no selectable/predicate scope check, so they are the
control: unchanged within noise, confirming the gain comes from the reordered
checks rather than run drift. `dataclasses.replace` remains the next bottleneck
to target.
