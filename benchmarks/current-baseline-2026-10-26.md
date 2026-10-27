# Current comparative runtime and capacity baseline, 2026-10-26

Closes the measurement work in #548; the completed-burst test correction addresses
#551. Raw JSON, exit statuses, stderr, exact commands, host snapshots and checksums
are in [`results/2026-10-26-current/`](results/2026-10-26-current/).

## Scope and provenance

- Measured source: `0bb5ab1ff0d2a47b9aa017e621d293f0d2b7aff1`; every report has
  `dirty: false`. Findings/evidence are added in a subsequent evidence-only commit.
- **86 completed ordinary-mode measurement runs**, all exit zero and empty stderr. **76** cover the intended
  matrix (**1,368 adapter trials**); ten exploratory runs are explicitly excluded
  from reported comparisons, rather than relabelled as above-capacity evidence.
  Across accepted timing/diagnostic/memory runs: **1,526,976 completed operations**,
  **23,083,200 returned/validated rows**. These are correctness totals, not an
  aggregate throughput metric or independent statistical samples.
- Six rounds per process cover every adapter permutation. Five observer contrasts
  additionally use fresh-process off/on then on/off blocks, giving 12 trials per
  adapter/condition. Other summaries have six trials. Configurations are not a
  randomized factorial experiment; thermal/cache/host activity remain uncontrolled.
- All configured pool slots are retained simultaneously, policy-probed and prepared
  outside timing. Raw aiosqlite/aiomysql use a bounded free-connection queue; snekql
  and Core use bounded pools, Core with zero overflow. No library runtime code was
  changed in this unit. Raw-driver pooling does not provide snekql's lifecycle contract.
- Identical returned values are validated using the same strict Pydantic result
  contract. Reads and streams acknowledge transaction commit. Bulk inserts commit,
  then independently read back/validate the inserted identities in a second committed
  transaction. Observed rows, identity sums, payload bytes and operation counts were
  checked across all 86 runs. No failed/uncertain write is replayed.

### Environment

- CPython **3.15.0**, Linux `7.2.8-9-omarchy`, glibc 2.44, asyncio Unix selector,
  GC enabled. Intel Core i7-14700F, 28 logical CPUs/all 28 in affinity;
  33,454,792,704 physical-memory bytes; CPU-zero governor `powersave`.
- Samsung SSD 990 PRO 2TB; private temporary files on Btrfs with `zstd:3`
  compression. Roughly 1.1 TiB available at capture start. No CPU pinning, frequency
  override or measurement CPU quota. This agent ran no local suite/build during
  capture; unrelated worktrees/host activity were not isolated or exhaustively
  audited. Host load and pressure snapshots are retained.
- SQLite **3.53.1**, file-backed WAL/NORMAL, foreign keys on, 5000 ms busy timeout.
  MariaDB **13.0.2**, owned loopback TCP server, InnoDB flush-at-commit 1,
  binary logging off, sync_binlog 0, 16384-byte pages; REPEATABLE READ, UTC,
  utf8mb4 and verified strict/integrity session policy on every connection.
  These two engines do **not** have equivalent power-loss durability policies.
- snekql **0.9.0**, aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1,
  greenlet 3.5.6, Pydantic 2.14.0, pydantic-core 2.50.0,
  PyMySQL 1.2.0, AnyIO 4.15.1. No dependency changed in this unit.
- `uv.lock` SHA-256:
  `7e622ca52611bcfed193b5d167f2eb1856ccc855ed5133c7fff6c1c9808210bc`.

Capture: **2026-10-25T23:33:58.083599+00:00–2026-10-25T23:53:10.967577+00:00 UTC**. Findings were
compiled on 2026-10-26. One-minute host load was 3.60 at start
and 3.21 at end; this is context, not a pass threshold.

## Work and summary definitions

| Workload | Operations/trial | Rows in fixture | Warmup | Batch |
| --- | ---: | ---: | ---: | ---: |
| Point / join | 2000 | 2000 | 200 | one returned row |
| Verified bulk | 100 inserts + readbacks | separate write table | 10 | 64 rows |
| Stream, one worker | 4 complete scans | 5000 | 1 | 64 / 256 |
| Stream, eight active workers | 16 complete scans | 5000 | 1 | 64 / 256 |

Widths are 32/4096 ASCII bytes, with 8192-character MariaDB VARCHAR capacity in
all cases and SQLite TEXT. Payloads repeat `x`/`j`: they are highly compressible,
not production entropy, Unicode, BLOB, network-byte or storage-bandwidth probes.
The seeded datasets fit memory; point identities are sequential, not a production
popularity distribution. Dataset size, warmup and query/result construction remain
part of the precise contract in [comparison.md](comparison.md).

Values below are medians across per-adapter trials; brackets are trial min–max.
`p99` is the **median of per-trial p99s**, not a pooled population percentile or
confidence bound. No statistical significance claim is made. Additional descriptive
summaries, rows/s, payload MiB/s, loop delay and profile labels are in
[`summary.csv`](results/2026-10-26-current/summary.csv). Primary tables exclude
memory/acquisition profiling and counting observation unless explicitly stated.

## Narrow point reads and pool geometry

| Backend | Pool / workers | N | Raw ops/s | snekql ops/s [min–max] | Core ops/s | snekql p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sqlite | 1 / 1 | 6 | 11,812.3 | 3,004.5 [2,714.5–3,397.4] | 2,958.4 | 0.593 |
| sqlite | 1 / 8 | 6 | 10,870.9 | 2,035.3 [2,020.5–2,422.2] | 2,803.0 | 5.883 |
| sqlite | 4 / 1 | 6 | 7,127.0 | 2,624.3 [2,490.3–2,965.7] | 1,995.8 | 0.674 |
| sqlite | 4 / 4 | 12 | 7,164.8 | 2,071.1 [2,002.3–2,340.5] | 1,852.7 | 3.083 |
| sqlite | 4 / 16 | 12 | 7,836.1 | 1,637.4 [1,483.3–1,763.0] | 1,833.4 | 12.592 |
| mariadb | 1 / 1 | 6 | 9,882.8 | 2,357.4 [2,272.3–2,520.7] | 2,765.5 | 0.774 |
| mariadb | 1 / 8 | 6 | 8,481.8 | 1,778.9 [1,620.8–1,844.6] | 2,386.9 | 7.515 |
| mariadb | 4 / 1 | 6 | 8,000.5 | 2,027.7 [1,957.2–2,058.4] | 2,404.1 | 0.871 |
| mariadb | 4 / 4 | 12 | 14,940.0 | 2,853.7 [2,756.7–3,028.4] | 3,485.7 | 1.773 |
| mariadb | 4 / 16 | 12 | 14,799.3 | 2,296.4 [1,981.0–2,446.7] | 3,393.6 | 8.363 |

On this workload, increasing SQLite capacity did not improve throughput; p4/w16
was slower with a much larger tail than p1/w1. MariaDB improved at p4/w4 but
lost throughput and increased tail latency at p4/w16. More admitted work is not
a universal speedup. These are closed-loop workers with predetermined work counts,
not measured fairness, an offered-arrival-rate saturation curve, queueing-model
fit, sustainable service capacity or an SLO recommendation.

## Width, joins and verified writes

| Backend | Case | Raw ops/s | snekql ops/s | Core ops/s | snekql p99 ms |
| --- | --- | ---: | ---: | ---: | ---: |
| sqlite | point-wide-p4-w4 | 7,039.4 | 2,049.7 | 1,814.8 | 3.081 |
| sqlite | join-narrow-p4-w4 | 7,505.1 | 1,901.1 | 1,794.3 | 3.321 |
| sqlite | join-wide-p4-w4 | 7,909.2 | 1,915.8 | 1,866.7 | 3.287 |
| sqlite | bulk-narrow-p1-w1 | 2,516.5 | 545.8 | 355.5 | 2.803 |
| sqlite | bulk-narrow-p4-w4 | 1,574.4 | 416.9 | 306.7 | 17.618 |
| sqlite | bulk-wide-p4-w4 | 757.3 | 357.6 | 300.9 | 26.249 |
| mariadb | point-wide-p4-w4 | 14,695.1 | 2,831.5 | 3,465.8 | 1.783 |
| mariadb | join-narrow-p4-w4 | 15,557.8 | 2,593.1 | 3,218.0 | 2.069 |
| mariadb | join-wide-p4-w4 | 14,773.0 | 2,473.4 | 3,060.7 | 2.030 |
| mariadb | bulk-narrow-p1-w1 | 165.5 | 124.2 | 123.7 | 12.028 |
| mariadb | bulk-narrow-p4-w4 | 376.5 | 375.2 | 293.4 | 15.552 |
| mariadb | bulk-wide-p4-w4 | 381.7 | 268.5 | 268.0 | 26.063 |

Bulk ops/s means a **64-row acknowledged INSERT plus a separate validated
readback**, not rows/s or INSERT-only speed. MariaDB benefited from concurrent
bulk work here; SQLite did not. Wide bulk writes reduced throughput on both.
Point-width differences were smaller/noisier; these results do not support a
universal per-byte cost model or a causal diagnosis of locks, fsync or CPU.

## Streaming and bounded batches

Each operation below scans 5000 rows; ops/s × 5000 gives validated rows/s.

| Backend | Width / pool / workers / batch | Raw scans/s | snekql scans/s | Core scans/s | snekql p99 ms |
| --- | --- | ---: | ---: | ---: | ---: |
| sqlite | 32 / 1 / 1 / 64 | 75.5 | 34.5 | 45.4 | 37.256 |
| sqlite | 32 / 1 / 1 / 256 | 78.4 | 47.8 | 45.3 | 25.861 |
| sqlite | 4096 / 1 / 1 / 64 | 60.1 | 29.3 | 33.7 | 40.622 |
| sqlite | 4096 / 1 / 1 / 256 | 66.5 | 36.7 | 43.0 | 32.102 |
| sqlite | 32 / 4 / 8 / 64 | 33.7 | 22.2 | 24.3 | 390.821 |
| sqlite | 32 / 4 / 8 / 256 | 37.4 | 26.0 | 28.5 | 328.936 |
| mariadb | 32 / 1 / 1 / 64 | 78.5 | 43.4 | 51.7 | 23.134 |
| mariadb | 32 / 1 / 1 / 256 | 83.0 | 45.5 | 53.3 | 22.179 |
| mariadb | 4096 / 1 / 1 / 64 | 47.3 | 29.7 | 33.4 | 34.520 |
| mariadb | 4096 / 1 / 1 / 256 | 47.6 | 31.8 | 35.3 | 33.245 |
| mariadb | 32 / 4 / 8 / 64 | 77.5 | 42.1 | 49.5 | 191.937 |
| mariadb | 32 / 4 / 8 / 256 | 83.0 | 46.3 | 53.6 | 173.758 |

Batch 256 generally improved scan throughput over 64 in these samples. Multiple
concurrent scans increased tail latency and did not imply proportional aggregate
throughput. Every delivered batch was bounded and every row checked online;
that is not a bound on socket buffers, native allocations or process RSS.

### Scoped allocation diagnostics — not primary timing

For wide single-worker streams, peak traced Python bytes below include the common
consumer, worker/probe tasks and latency retention, after warmup/GC. They exclude
setup/server/serialization and do not cover all native memory.

| Backend | Batch | Raw peak KiB | snekql peak KiB | Core peak KiB |
| --- | ---: | ---: | ---: | ---: |
| sqlite | 64 | 552.9 | 626.2 | 584.2 |
| sqlite | 256 | 2,168.9 | 2,428.7 | 2,240.9 |
| mariadb | 64 | 1,060.7 | 1,122.2 | 1,090.6 |
| mariadb | 256 | 2,658.8 | 2,802.3 | 2,706.1 |

Raw before/after resident snapshots are retained, not interpreted as peak RSS or
leak evidence. Increasing batch size trades memory for throughput in these
observations; one dataset size cannot certify row-count-independent memory.

## Counting-observer contrasts

Twelve trials per adapter/condition, with fresh-process off/on then on/off blocks.
The synchronous observer retains event-kind/phase counters only. This is **not**
OpenTelemetry export, logging or production collector overhead. Raw/Core remain
uninstrumented reference adapters in both conditions.

| Backend | Case | Off ops/s [min–max] | On ops/s [min–max] | On/off median ratio |
| --- | --- | ---: | ---: | ---: |
| sqlite | point-narrow-p4-w4 | 2,071.1 [2,002.3–2,340.5] | 1,872.1 [1,787.3–2,131.4] | 0.904 |
| sqlite | point-narrow-p4-w16 | 1,637.4 [1,483.3–1,763.0] | 1,486.7 [1,375.0–1,621.9] | 0.908 |
| sqlite | point-wide-p4-w4 | 2,049.7 [1,914.7–2,155.5] | 1,866.5 [1,672.5–2,029.5] | 0.911 |
| sqlite | stream-wide-p1-w1-b256 | 36.7 [31.5–42.2] | 38.7 [30.6–43.5] | 1.054 |
| sqlite | stream-narrow-p4-w8-b256 | 26.0 [24.4–28.1] | 24.6 [23.4–26.6] | 0.947 |
| mariadb | point-narrow-p4-w4 | 2,853.7 [2,756.7–3,028.4] | 2,563.2 [2,526.6–2,641.0] | 0.898 |
| mariadb | point-narrow-p4-w16 | 2,296.4 [1,981.0–2,446.7] | 2,123.1 [1,904.4–2,283.4] | 0.925 |
| mariadb | point-wide-p4-w4 | 2,831.5 [2,673.7–3,056.2] | 2,495.4 [2,434.4–2,616.8] | 0.881 |
| mariadb | stream-wide-p1-w1-b256 | 31.8 [24.5–34.9] | 32.5 [29.6–34.2] | 1.022 |
| mariadb | stream-narrow-p4-w8-b256 | 46.3 [45.0–46.8] | 44.7 [43.8–45.6] | 0.966 |

Point-read counting runs had lower median throughput here. Wide single-worker
stream counting runs had slightly higher medians: **do not interpret that as an
observer speedup**. The wide-stream ranges overlap; these runs do not isolate all environmental
variation. These are descriptive matched-configuration observations, not a stable
percentage overhead budget, optimization attribution or CI gate.

## Acquisition diagnostics

A separate narrow p4/w16 profile records raw free-queue wait, public snekql
admission events and Core connect checkout. The last includes bookkeeping/reset
and is **not** the same interval as admission wait. Do not rank these values as
like-for-like queue latency.

| Backend | Raw p99 / max ms | snekql p99 / max ms | Core p99 / max ms |
| --- | ---: | ---: | ---: |
| sqlite | 0.001 / 239.617 | 10.151 / 11.073 | 14.375 / 21.446 |
| mariadb | 0.001 / 91.268 | 5.857 / 6.753 | 12.240 / 16.042 |

Both statistics are medians of the respective per-trial values. A very low raw
p99 hid a much larger maximum: a few long waits need not affect the 99th percentile.
The raw free-connection queue does not duplicate snekql's FIFO/no-barging gate;
new getters can take a returned item before a notified getter resumes. This is a
bounded raw-driver reference, **not equivalent admission-fairness guarantees**.
The pattern is consistent with that distinction, not a causal scheduler trace.
Predetermined equal worker totals are not proof of equal service or fairness.

## Validation, corrections and limits

- Clean measured-code revision: full local `uv run snektest tests` —
  **4,155 passed in 1118.99 seconds**; exit zero. The earlier development-focused
  native comparative/service/fixture suite passed **106 in 242.77 seconds**.
- Forced-lazy test runner over those focused files: **106 passed in 304.53 seconds**.
  Its fresh subprocesses do not automatically inherit `-X`; this alone is not
  end-to-end forced-lazy comparator validation.
- Separate direct `-X lazy_imports=all` probes: **16 raw/snekql CLI cases passed**
  (both backends × four workloads), with real capacity two, four workers, wide
  payloads and counting enabled. **Eight all-adapter cases failed**, with no JSON
  success report, at SQLAlchemy 2.1.1 `Table.dispatch` initialization. A minimal
  SQLAlchemy-only command reproduces without importing snekql. See
  [the separately tracked limitation](https://github.com/crpier/snekql/issues/558). No dependency or import-filter
  workaround was applied. These validation probes are not baseline performance
  trials; neither failures nor partial work are relabelled as passes.
- Local ty, Ruff lint/format, generated-interface and lock checks passed. No full
  current forced-lazy suite or new cross-platform/native-version matrix is claimed.

- The initial eight-worker stream commands requested only four operations, so
  only four workers had work. All ten affected runs passed their actual work
  contract, but **do not** establish above-capacity stream behavior. They remain
  in the manifest with `coverage_accepted: false`. Ten fresh-process replacements
  use 16 operations, all eight workers actually complete work, and retain the
  same clean revision. Only the 76 accepted runs enter summary.csv and these tables.
- Development/TDD failures are retained separately from measured success. The
  service smoke now waits for five completed measured bursts rather than requiring
  five within two seconds. The old assertion failed under an owned 5%-CPU scope;
  the explicit-work replacement passed. Those quotas applied only to owned test
  processes, never to comparative measurements or other worktrees.
- Historical #540 race calibration: one preliminary and five counted smoke probes
  did **not** re-trigger the race after temporarily removing its notification fix.
  The fix was restored before the measured commit. These are not failing-before
  evidence or a deterministic scheduler regression claim; original #540 evidence
  remains distinct. Native scheduling coverage is bounded, not exhaustive.
- #546's final evidence-only CI first attempt was cancelled while still progressing
  and contained a service-test failure without its final traceback. Its target-only
  rerun passed. The controlled CPU reproduction does not prove the cause of that
  original CI failure; #551 records that limitation.
- Repository CI workflows were `disabled_manually` during this unit. Their state
  was left untouched. **No #555 GitHub CI matrix, CodeQL or dependency-review pass
  is claimed.** Local validation details/statuses are recorded with the artifacts.
- The September baseline used Python 3.14.2, different dependencies/engines,
  fixed capacity/width and a different stream dataset. Do not attribute cross-date
  changes to snekql alone. No runtime optimization is claimed by this work.
- These are local plaintext/nonreplicated fixtures, not target-platform qualification,
  TLS/WAN, failover, power-loss durability, a long-running memory test, or release
  certification. Repeat on the intended release revision/environment after concurrent
  API/migration work and any separately managed dependency updates. This unit does
  not touch that work or remediate dependencies.

## Reproduction and next use

See the artifact README for checksum verification and sequential accepted-command
replay from the exact clean revision. Native tools are not installed/upgraded by
the harness. Keep engine/interpreter/dependency/policy metadata aligned, or label
the result a new baseline. Never mix timing and diagnostic/memory summaries.

Use these measurements to choose representative application workloads, contention
and instrumentation budgets for qualification—not to set a universal default pool
size or a percentage timing CI gate. Investigate repeatable differences using
matched clean revisions and noise-aware order-balanced reruns before optimizing.
