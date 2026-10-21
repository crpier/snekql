# aiomysql versus asyncmy — 2026-10-21

Tracking: [#478](https://github.com/crpier/snekql/issues/478).
Method: [direct driver benchmark](mariadb-drivers.md).
Raw reports: [results/2026-10-21-drivers](results/2026-10-21-drivers/).

## Conclusion

**asyncmy is a strong candidate for a compatibility prototype, especially for
read-heavy workloads. This is not yet a recommendation to switch drivers.**

On this host, asyncmy's median verified throughput was **5.49–5.97×** aiomysql
for buffered 10,000-row scans, **4.62–4.68×** for streaming scans, and
**1.28–1.44×** for point reads. Single-row committed writes were essentially tied;
batched writes showed only a small, noisy improvement. A driver switch cannot
be expected to remove the cost of durable server commits.

These results include identical tuple/value/order/cardinality checks, transaction
commands and, for writes, transactional readback. They are not isolated packet
parser timings or predictions of full snekql application speedups.

## Environment and provenance

- Clean source: `2dd8009fe955f18544c55c6a00e63d7cbd5a52b3`.
  Branch base: `cb4db57a18f44be1d2e76ad815c214095bf10f6f`.
- aiomysql **0.3.2**, PyMySQL **1.2.0**, asyncmy **0.2.16**.
- CPython **3.15.0**, standard asyncio selector loop, GC enabled.
- MariaDB **13.0.2**, `innodb_flush_log_at_trx_commit=1`, binary logging off,
  `sync_binlog=0`, 16 KiB InnoDB pages. This is the installed local server, not
  a cross-version assessment of the project's maintained LTS targets.
- Intel Core i7-14700F, 28 logical CPUs, approximately 31.2 GiB RAM,
  Linux 7.2.8-9-omarchy, x86-64. CPU-zero governor: `powersave`; affinity unrestricted.
- Server data under a private `$HOME/.cache` directory on **Btrfs**, not tmpfs.
  Loopback TCP, no TLS. Actual temporary data paths and per-connection policies
  are recorded in each report; no database credentials are recorded.
- uv **0.13.4**, versus CI's pinned 0.13.0. The benchmark overlay was pinned with
  `--with asyncmy==0.2.16`; neither `pyproject.toml` nor `uv.lock` changed.

Both drivers share the same privately owned server within each command. Each
trial opens fresh connections, verifies settings, warms each connection, and
alternates driver order. Six trials per driver give each driver three first and
three second positions. Eight-worker cases use eight dedicated connections,
not a shared connection or a native pool.

Other checkout test suites were allowed to finish before measurement. This was
still an ordinary desktop host with background applications, not an isolated
machine, fixed CPU clock, or controlled thermal experiment.

## Throughput

Entries are **median operations/sec across six trials**, with minimum–maximum
individual-trial throughput in parentheses. Ratio is the ratio of medians, not a
confidence interval. A scan operation consumes all 10,000 rows. A write operation
includes INSERT/COMMIT and a separate readback transaction. Bulk operations insert
128 rows each.

| Workload | Connections | aiomysql ops/s (range) | asyncmy ops/s (range) | Ratio |
| --- | ---: | ---: | ---: | ---: |
| point-read | 1 | 13,246.7 (12,124.3–13,561.8) | 17,010.1 (15,377.7–17,832.0) | 1.28× |
| point-read | 8 | 20,931.9 (20,547.6–21,866.8) | 30,199.4 (29,862.7–33,290.0) | 1.44× |
| buffered | 1 | 67.9 (65.8–68.5) | 372.7 (363.6–375.4) | 5.49× |
| buffered | 8 | 68.0 (67.0–68.2) | 405.9 (385.4–411.4) | 5.97× |
| stream | 1 | 59.1 (58.3–60.4) | 276.3 (261.6–280.2) | 4.68× |
| stream | 8 | 60.3 (60.1–61.1) | 278.5 (268.8–285.6) | 4.62× |
| write | 1 | 182.5 (129.2–185.4) | 182.1 (124.3–188.8) | 1.00× |
| write | 8 | 795.6 (699.8–798.5) | 788.7 (775.8–797.3) | 0.99× |
| bulk | 1 | 161.0 (140.0–167.2) | 172.3 (143.6–175.0) | 1.07× |
| bulk | 8 | 780.5 (563.3–788.0) | 786.2 (704.6–793.7) | 1.01× |

The scan advantage is large and consistent across these trials. Point-read
results were noisier in an initial 5,000-operation pass, including an unusually
slow asyncmy eight-worker trial. Both point-read cases were therefore rerun with
**50,000 operations and 1,000 warmups per connection**, rather than dropping an
outlier. The table uses these longer runs; the initial reports remain under
[`preliminary/`](results/2026-10-21-drivers/preliminary/).

Write differences are small relative to observed run variation. In particular,
**do not interpret 1.07× bulk throughput as an established 7% application gain**.
Durable-commit and host/storage costs are consistent with the weak write-side
difference, but no server CPU/I/O profile was collected to prove the bottleneck.

## Responsiveness

For buffered scans, median per-trial heartbeat p99 lateness changed from:

- One connection: **10.17 ms → 0.76 ms**.
- Eight connections: **82.42 ms → 15.83 ms**.

This supports a responsiveness benefit for buffered large reads in this workload,
although eight concurrent buffered scans still cause meaningful stalls.
Streaming throughput improves strongly, but its eight-connection median heartbeat
p99 is nearly unchanged (**5.33 ms → 5.14 ms**). The worst recorded streaming
stall was **23.92 ms for asyncmy versus 7.97 ms for aiomysql**, so this run does
**not** support a blanket claim that asyncmy always improves worst-case stalls.
Heartbeat lateness includes OS scheduling. Each report retains operation latency
and heartbeat summaries rather than pooling percentiles across trials.

## Reproduce

```sh
root=$(mktemp -d "$HOME/.cache/snekql-drivers-XXXXXXXX")
mkdir "$root/tmp"
for workers in 1 8; do
  for workload in point-read buffered stream write bulk; do
    case "$workload" in
      point-read) operations=50000; warmup=1000 ;;
      buffered|stream) operations=100; warmup=5 ;;
      write) operations=1000; warmup=20 ;;
      bulk) operations=200; warmup=5 ;;
    esac
    TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
      -m benchmarks.mariadb_drivers --workload "$workload" \
      --operations "$operations" --warmup "$warmup" --rows 10000 \
      --trials 6 --workers "$workers" --batch-size 128 \
      >"$root/$workload-w$workers.json" \
      2>"$root/$workload-w$workers.stderr" || exit
  done
done
```

Actual collection ran the shorter point-read pass alongside the other cases,
then repeated just point reads at the longer settings above. Do not run other
benchmarks or test suites concurrently when attempting to reproduce the ratios.
Scan trials are short, especially with asyncmy; increase scan operation counts
for stronger latency-tail claims or publication on a controlled host.

## Candidate review and validation

asyncmy 0.2.16 was not yanked at review time. Its
[release notes](https://github.com/long2ice/asyncmy/releases/tag/v0.2.16) describe
closed-stream connection teardown and unbuffered dictionary-cursor fixes.
The benchmark uses tuple cursors and normal closure, not a teardown-failure audit.
Its tagged README also documents native prepared statements; **this benchmark
uses the common text-protocol cursor path for both drivers**, not that extra API.

PyPI advertised Python >=3.9 but published no CPython 3.15 wheel for this release.
uv built it successfully from source on this machine. That is local build evidence,
not a portability guarantee. The available system compiler was GCC 16.2.1.
A GitHub advisory lookup for asyncmy 0.2.16 returned no entries on 2026-10-21;
this is not a comprehensive dependency/security audit.

Validation:

- TDD: new command initially failed its real-driver CLI test; point reads then
  passed. Added concurrent scan/write cases initially failed on unsupported CLI
  options, then passed after implementation.
- **13 targeted benchmark tests passed**, including fault guards for wrong
  result values, lost writes, and streaming accidentally using `fetchall()`.
- Initial full-suite run failed with shared `/tmp` **disk quota exceeded**:
  2,148 passed, 15 failed, 21 errored before abort. MariaDB preallocation failures
  affected existing and new tests. The log was preserved outside the checkout.
- With a private disk-backed `TMPDIR`,
  `PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest tests`:
  **3,909 passed in 1,570.78 seconds**.
- `uv run ty check`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- All ten final benchmark configurations succeeded; each contains twelve trials.
  The two preliminary point-read reports are retained as well.

## Next decision

A separate compatibility prototype should evaluate snekql's private aiomysql
integration points: result completion without loading additional result sets,
warning suppression/redaction, cancellation and uncertain commit outcomes,
streaming abandonment, connection initialization/reset/recycling, TLS and binary
value binding. Also test Python 3.15 build/install availability in supported CI
platforms and maintained MariaDB series.

If those checks pass, an end-to-end snekql comparison would show how much of the
raw-driver improvement survives query construction, validation and lifecycle
handling. Native prepared statements deserve a separate experiment, not an
unannounced change in this apples-to-apples comparison.
