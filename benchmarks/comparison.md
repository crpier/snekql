# Comparative runtime measurements

The command covers buffered point reads and bounded
streaming scans, indexed joins and verified bulk writes on SQLite and MariaDB.
It also measures capacity-one pool contention and provides separate pool and
memory diagnostic profiles. [Published results and regression guidance](findings.md)
include raw artifacts and exact commands. Do not treat a tiny local run as a
complete performance assessment.

## Run from a source checkout

```sh
uv sync --locked --all-extras
mkdir -p "$HOME/.cache"
root=$(mktemp -d "$HOME/.cache/snekql-compare-XXXXXXXX")
mkdir "$root/tmp"
TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
  uv run python -m benchmarks.compare --backend sqlite --adapter all \
  --operations 1000 --rows 1000 --trials 3 --warmup 100 \
  >"$root/report.json" 2>"$root/stderr.log"
```

Check the exit status before consuming the report. The command prints one JSON
document only after every trial succeeds. A failed operation aborts the command;
completed trials are not averaged into a successful partial report. SQLAlchemy
and greenlet are development dependencies, not snekql runtime dependencies.

Use `--backend mariadb` for an owned, temporary MariaDB server on loopback TCP.
Install `mariadbd`, `mariadb-install-db` and `mariadb` first. Startup, bootstrap and
shutdown are outside the timed region. Missing tools fail the command, rather
than silently skipping the requested comparison. No existing database is used.

`--adapter` accepts `all`, `raw`, `snekql`, and `sqlalchemy`. `--workload` accepts
`point-read`, the default, `stream`, `join`, or `bulk`. For a scan, one operation means reading the
entire seeded dataset, so use fewer operations:

```sh
TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
  uv run python -m benchmarks.compare --backend mariadb --adapter all \
  --workload stream --batch-size 256 --rows 10000 \
  --operations 3 --trials 3 --warmup 1 >"$root/stream.json" 2>"$root/stream.stderr"
```

Bounds are:

| Option | Default | Accepted range |
| --- | --- | --- |
| `--operations` | 1000 | 1 through 100000, per trial |
| `--rows` | 1000 | 1 through 1000000 |
| `--trials` | 3 | 1 through 30, per adapter |
| `--warmup` | 100 | 0 through 10000, before each trial |
| `--batch-size` | 256 | 1 through 10000, per stream batch or bulk INSERT |
| `--workers` | 1 | 1 through 128, sharing capacity one |

`all` rotates the starting adapter each round. Three rounds give each adapter
each position once. Runs are sequential in one process, not isolated subprocess
memory experiments. This rotation reduces fixed order bias; it does not remove
thermal drift, scheduler noise, or cache effects.

## Equivalent application work

Within a run, all adapters read the same privately owned database. SQLite uses
a file; MariaDB uses an InnoDB table in the temporary server. Seed identities are contiguous from one; point reads select the next identity,
wrapping at `--rows`. Streaming selects every row in primary-key order. Rows have an integer ID, an email string and a 32-byte ASCII
payload. No random-number generation occurs in the timed operation.

Each operation uses explicit SQL BEGIN and acknowledged COMMIT, consumes the
complete result, and validates each row once against the same strict Pydantic
result contract. Common correctness checks also compare actual values, order
and cardinality against the seeded records, including during warmup. It records observed row counts and identity sums, not planned work counts.

SQLite uses WAL, NORMAL synchronization, foreign keys on, and a 5000 ms busy
timeout. MariaDB uses utf8mb4, REPEATABLE READ, UTC and the same strict SQL mode
and integrity checks as snekql. Each MariaDB adapter probes the actual session
before timing; a policy mismatch aborts the comparison. Reported server metadata
includes VERSION(), redo flush policy, binary logging, sync_binlog and page size.

Every adapter has capacity one. Raw aiosqlite/aiomysql retains one connection
behind a FIFO asyncio lock held from before BEGIN through commit/rollback.
Snekql and SQLAlchemy acquire their own size-one pools per transaction. Their checkout and reset costs remain part of the
comparison. This is a raw-driver baseline, not a claim that either raw driver provides
snekql's lifecycle guarantees. MariaDB raw and Core clients explicitly BEGIN,
consume results, validate, and COMMIT; they do not rely on implicit transaction
start or autocommit. Point reads buffer their one-row result.

Streams use native `fetchmany`, snekql `fetch_chunks`, or SQLAlchemy Core `stream`
with bounded partitions and `yield_per`. Raw MariaDB uses an unbuffered SSCursor.
The common consumer keeps only row/batch counts and an identity sum. It validates
each expected identity as it arrives, so a duplicate or missing row cannot hide
behind a plausible checksum. Every adapter checkpoints after consuming a batch.
The runner does not accumulate a full scan result. Batch size bounds delivered
partitions, not total process RSS, driver socket buffers, or setup allocations.
Tests forbid result-bearing native `fetchall` calls during streaming.

The snekql adapter constructs a Query Builder named projection each operation;
the SQLAlchemy adapter constructs a Core select each operation. Raw aiosqlite
uses parameterized SQL. No ORM sessions are used. Native SQLite statement caching
and SQLAlchemy's default compiled cache remain enabled. This measures normal
execution paths, not isolated compilation cost or precompiled-query execution.
Setup, seeding, connection initialization and warmup are outside measurement.

## Joins and verified bulk writes

`join` reads one user and its related profile through an indexed inner join.
The profile payload is different from the user's payload, so returning the base
row instead cannot pass validation. Each operation constructs its native query
or builder, explicitly begins a transaction, buffers and validates the one-row
projection, and commits.

`bulk` inserts `--batch-size` explicit identities in one parameterized multi-row
INSERT. All adapters use the same SQL statement shape, not a SQLite executemany
loop versus a multi-row statement. The INSERT transaction must acknowledge commit
before a second transaction reads back that identity range, validates every row,
and commits. Both transactions and input/query construction are timed. This is
verified bulk throughput, not a measurement of INSERT alone.

The write table is separate from the read/join dataset. Each trial deletes its
previous write rows before warmup, then deletes warmup rows before timing.
Logical starting state is identical; storage allocation and OS/server caches
are not reset. IDs do not wrap at `--rows`. A driver-fault test simulates a commit
reply without persistence; the missing readback must fail the command.

## Contention and diagnostic profiles

`--workers 8` puts eight tasks against capacity one. `--operations` is a total,
not a per-worker count. Workers receive disjoint operation indices and bulk IDs.
This tests application-side pool contention, not concurrent server-side writers
or cross-process SQLite file locks. Per-worker counts are predetermined and must
not be read as a fairness measurement. Latency includes actual acquisition wait.

Use `--profile timing`, the default, for primary comparisons. It installs no
snekql observer and records no pool samples. The common heartbeat still runs.
Use `--profile diagnostic` separately for acquisition measurements:

- Raw drivers report time acquiring the one-connection asyncio lock.
- Snekql reports its public `pool_wait` finish events, which measure admission.
- Core reports time awaiting `AsyncEngine.connect()`. This is **checkout**,
  including pool bookkeeping and possible physical connection work, not pure
  queue wait. Do not compare it numerically as if it were the same interval.

Only measured acquisitions count; setup, warmup and resets are excluded. Bulk
operations have two acquisitions, one for insertion and one for readback.
Snekql observation instruments more than pool events even when the collector
only keeps pool samples. Diagnostic throughput is therefore not interchangeable
with primary timing throughput.

`--profile memory` starts tracemalloc after setup, warmup and a GC pass. It stops
before connection/server teardown or JSON serialization. It reports peak and
current traced Python bytes, including worker tasks, correctness checks and
measurement recorders. These are incremental allocations in that window, not
total application memory or complete native allocator coverage. Latency sample
retention grows with operation count; compare identical configurations.

Linux also reports resident-memory snapshots immediately before and after the
window. These are not peak RSS measurements and can reflect allocator retention
or unrelated process activity. Other platforms report null resident snapshots.
No process-lifetime high-water mark is attributed to the workload: setup seeding
allocates its input dataset before measurement. Memory-profile timings are
instrumented and must not be mixed with timing-profile results. An interpreter
already running tracemalloc is rejected rather than silently resetting its data.

## Report version 1

- `configuration` records workload sizes and the policies above.
- `environment` records Python, loaded SQLite, package versions, OS, architecture,
  logical CPUs, event-loop class, GC state, Git commit and dirty-tree status.
  `hardware` adds Linux CPU model, physical memory, process affinity and the
  CPU-zero governor when available. Unsupported or inaccessible facts are null.
  Publication needs an identifiable clean source revision; neither CPU frequency
  nor host background activity is controlled by this command.
- `trials` keeps each adapter/round separately, with completed-operation latency
  count, mean, p50, p99 and maximum in milliseconds. Percentiles interpolate the
  ordered samples; tiny trials are correctness checks, not useful tail estimates.
- `elapsed_seconds` and `throughput_ops_s` include common loop bookkeeping and
  correctness checks. Per-operation latency includes construction, transaction
  entry, execution, validation, correctness checks, commit and return. Reports
  from the earlier point-read prototype excluded post-read checks and must not
  be compared directly with this timing definition.
- `observed` records the returned row count and identity sum. Throughput is in
  completed operations per second, not rows per second.
- `stream` records consumed batch count and largest delivered batch, or null for
  point reads. Warmup batches and rows are excluded.
- `loop_stall` records wakeup lateness for a common 5 ms heartbeat during timed
  work, in milliseconds. Only completed wakeups count. No samples means null
  summaries, not a claimed zero stall. This includes OS scheduling delay and is
  not a direct CPU-time measurement. The same probe runs for every adapter.
- `pool` identifies the acquisition metric and sample summary, or null when
  disabled. `memory` holds scoped allocation/resident measurements, or null.
- `per_worker_operations` records completed requests for each task.
- `measurement` records the profile, heartbeat interval and timing scope. Heartbeat
  shutdown, setup and warmup are outside elapsed workload time.
- `session_policy` records the probed MariaDB session values for each trial.
  SQLite currently reports null here; its configuration fields describe the
  requested setup, not an additional benchmark-level probe.

No latency or throughput value is a CI pass threshold. CLI tests check observed
work, argument bounds, trial ordering and report configuration. An injected
50 ms driver callback block checks the heartbeat, not machine throughput.
See [the published baseline](findings.md) for repeated results and noise-aware
regression review.
