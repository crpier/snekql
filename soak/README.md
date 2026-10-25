# Resource soaks (source checkout only)

These Linux commands are opt-in reliability workloads, not installed APIs or
comparative performance benchmarks. Run from a clean checkout with locked dev
dependencies. They own disposable databases; neither accepts an existing database
path or credentials. MariaDB requires native server/client tools and uses an
owned loopback TCP server, without production TLS. No machine-wide fault settings
are changed.

- `python -m soak.lifecycle`: repeated database open/close cycles; see the
  [failure inventory](../docs/failure-matrix.md#optional-resource-soak).
- `python -m soak.service`: **one long-lived Database** with concurrent mixed
  workloads, periodic saturation and cancellation, and drained recovery.

## Reproduce a service run

Run each target sequentially in a fresh process; do not share writable fixture
directories or run suite/benchmark processes concurrently for capacity claims.
Use a private temporary directory on a filesystem with enough space for MariaDB.

```sh
uv sync --locked --all-extras
root=$(mktemp -d "$HOME/.cache/snekql-service-XXXXXXXX")
mkdir "$root/tmp"
for backend in sqlite mariadb; do
  for pool in 1 4; do
    status=0
    TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
      uv run python -m soak.service --backend "$backend" \
      --pool-size "$pool" --workers 16 --duration 1800 --warmup 10 \
      --sample-interval 10 --rows 257 --batch-size 32 \
      --slow-consumer 0.005 --burst-interval 1 --seed 538 \
      >"$root/$backend-$pool.jsonl" 2>"$root/$backend-$pool.stderr" || status=$?
    printf '%s\n' "$status" >"$root/$backend-$pool.status"
    [ "$status" -eq 0 ] || exit "$status"
  done
 done
printf 'Evidence: %s\n' "$root"
```

The manual **Service soak** workflow runs both backends with pool sizes one and
four, 16 workers, and MariaDB 11.4 LTS. It retains stdout, stderr and exit status
for 14 days, including failed runs. The default measured phase is 30 minutes;
workflow duration is limited to 1–3000 seconds under its 60-minute job limit.
Ordinary full-suite CI runs only short native CLI tests. Longer runs are not PR
correctness or throughput gates.

## Workload and correctness

After literal fixture migrations and schema verification, the runner fills all
admission slots, cancels a queued waiter and warms up the mixed workload. The
same Database then stays open for the measured phase:

- Every worker cycles through point read, write, full stream and early stream.
  A per-worker seeded RNG selects immutable read identities; scheduling is **not**
  deterministic. All read fields and ordered stream identities are checked against
  known fixture values. Streams reject empty/oversized batches and missing,
  reordered, duplicated or corrupted records, including the final partial batch.
- Each worker owns one separate ledger row. A write atomically increments its
  sequence and stores a worker/sequence/seed token. An independent Python count
  advances only after acknowledged transaction commit. After draining, all ledger
  identities, sequences and tokens must agree with acknowledged writes.
- Slow consumers pause after each delivered batch; early consumers close after
  the first batch. Neither streams nor transactions cross their owning task.
- Periodic bursts acquire all pool slots, retaining earlier leases while waiting
  for the rest, then cancel an additional provably queued waiter. They run beside
  normal workers. This is deliberately adversarial admission contention, not a
  representative arrival-rate model. It exposed [#540](https://github.com/crpier/snekql/issues/540).
- At the duration boundary, workers finish their current operation rather than
  cancelling active writes. A short phase still exercises all four operations
  per worker. All background tasks are joined. Occupancy/waiters must reach zero,
  the ledger and read fixtures are rechecked, and a fresh read must succeed.
  Shutdown must report closed with zero occupied capacity.

There is no error retry or allowed transient-error budget. An unexpected database
error, lost acknowledgement, invariant violation, drain failure or cleanup failure
fails the run. Acquisition and driver budgets use the runtime's 30-second defaults;
each whole worker operation/burst has an additional 60-second asyncio timeout.
Preparation/warm-up has a 120-second bound; final verification has 60 seconds.
Cleanup retains library ownership and can extend cancellation latency. Duration
excludes startup/warm-up/final verification and includes worker/burst drain time;
it is not a hard process-kill deadline.

The workload uses validated builder Table Models and atomic expression updates.
The fixture stays bounded: immutable read rows plus one ledger row per worker.
It does not exercise growing tables, joins, arbitrary models/codecs, connection
recycling, active-operation cancellation, real network/storage faults, migration
recovery or server-process memory. Those need separate workloads. Resource samples
measure only the Python client process.

## CLI bounds

Use `uv run python -m soak.service --help` for options. Bounds are validated before
resource allocation; non-finite floats are rejected.

| Option | Default | Bounds |
| --- | ---: | --- |
| `--backend` | required | `sqlite`, `mariadb` |
| `--duration` | 300 | 0.05–86400 seconds |
| `--warmup` | 5 | 0.05–300 seconds |
| `--sample-interval` | 5 | 0.01–300 seconds |
| `--pool-size` | 4 | 1–32 |
| `--workers` | 8 | 2–128 |
| `--rows` | 64 | 16–4096 immutable records |
| `--batch-size` | 16 | 1–1024 |
| `--slow-consumer` | 0.001 | 0.0001–0.05 seconds per batch |
| `--burst-interval` | 5 | 0.05–300 seconds between bursts |
| `--seed` | 538 | 0–4294967295 |

Valid bounds do not promise a workload will fit its operation/warm-up budgets.
For example, a very large result with tiny batches and long pauses may fail its
deadline. To test saturation, select more workers than pool slots.

## JSONL evidence contract, schema version 1

Every record has `schema_version: 1` and `kind`. Keep the entire file, stderr and
exit status together. Only exit zero **and** a final `summary` with
`status: "passed"` establish a completed run. A truncated file, missing summary,
failed cycle or an exception is not a passing subset. A caught exception emits a
`failure` record with its class, then propagates with a traceback on stderr;
termination/interrupts need not emit that record. Invalid arguments exit 2 before
any JSON. This development report schema is versioned but not a supported library
API.

Record kinds:

- `environment`: exact git revision and dirty flag, Python/OS/architecture/PID,
  all installed distribution versions, selected CLI configuration and histogram
  bucket upper bounds in milliseconds. A dirty tree is not a clean-revision claim.
- `engine`: actual loaded engine version, backend and initial public pool snapshot.
  SQLite is file-backed WAL with the runtime's default NORMAL durability; MariaDB
  uses the helper's native server defaults and runtime session policy. This is
  not a cross-backend durability or speed comparison.
- `sample`: phase (`baseline`, `load`, `drained`), elapsed monotonic seconds,
  resources, public pool snapshot and cumulative completed-operation counts for
  the measured phase. Baseline follows warm-up; final follows reconciliation.
- `summary`: exact completed counts, approximate latency percentiles, throughput,
  cumulative ledger counts (including warm-up), measured-only write counts,
  total and measured-only cancelled waiters, drained/closed snapshots, recovery
  result, final-minus-baseline resource deltas, and hard resource-check result.

Latency covers complete operations including acquisition, validation, slow
consumer pauses, commit and cleanup. `loop_delay` is wake-up lateness of a 10ms
heartbeat, **not** operation throughput. Histograms have 121 fixed logarithmic
upper bounds from 0.001ms through about 1074s, plus overflow; memory does not grow
with operation count. Counts, mean and max are exact; `p50_upper_ms`,
`p95_upper_ms`, and `p99_upper_ms` are upper bucket bounds (overflow uses observed
max). Empty metrics use JSON null, never NaN/infinity. Histogram buckets allow
later aggregation; percentiles from different runs should not be averaged.

Resource sampling runs GC and reads `/proc/self/status`, `/proc/self/fd` and
`/proc/self/task` in an asyncio worker thread. It records current/peak RSS in KiB,
file descriptors, native threads and Python threads. GC still competes for the
GIL and can delay the heartbeat. Sampling, JSON output, filesystem, allocator,
thread scheduling and host contention all perturb observations.

**Hard failures:** drained descriptors or native threads exceed the warmed-up
baseline; database/result/admission/cleanup invariants fail. Warm-up fills all
pool slots and starts the sampler before its baseline is taken.

**Reported, not thresholded:** RSS and peak-RSS changes. Current-RSS samples help
spot persistent trends, but allocator retention/page residency are not live-object
leak measurements. Peak RSS is a high-water mark, not a growth rate. Review raw
samples across longer/repeated runs; neither a flat trace nor a short clean run
proves universal leak freedom. Timing has no universal CI threshold.
