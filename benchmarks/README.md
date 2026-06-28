# snekql concurrency benchmarks

Standalone stress tests for runtime behavior under concurrent async load, kept
separate from the `snektest` unit suite. They answer the questions in
[issue #66](https://github.com/crpier/snekql/issues/66): pool fairness,
event-loop stalls during result materialization, and throughput/latency across
pool sizes and workload mixes.

## Running

```bash
# Everything available (SQLite + MariaDB if the binaries are installed)
uv run python -m benchmarks.run

# One backend, longer run, bigger dataset
uv run python -m benchmarks.run --backend sqlite --duration 5 --rows 20000

# Tune the sweep
uv run python -m benchmarks.run --pool-sizes 1 4 16 --worker-counts 1 8 32
```

MariaDB scenarios spin up a throwaway server via the project's
`TemporaryMariaDBServer` helper; they are skipped (with a message) when the
MariaDB binaries are not installed. No external server or credentials are
needed.

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

### 3. `fetch_all` materialization blocks the event loop — open follow-up

`Transaction.fetch_all` materializes and validates every row synchronously after
`fetchall()`. Selecting 20000 rows produced a **57 ms** (SQLite) / **115 ms**
(MariaDB) event-loop stall — long enough to delay every other task on the loop.
`fetch_chunks(...)` streams server-side and keeps stalls negligible; it is the
recommended path for large result sets. Filed as a follow-up to document the
guidance and consider chunked materialization yielding to the loop.

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
