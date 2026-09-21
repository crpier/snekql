# Comparative baseline, 2026-09-20

All 20 requested runs completed successfully. Raw JSON and exact argument lists
are in [`results/2026-09-20/`](results/2026-09-20/), including `manifest.json`. These are
local observations, not CI thresholds or universal capacity recommendations.

## Environment

- Clean runner revision: `cd24f93ab6989038128fdc6cdd520ff24157a8e1`. Each report records `dirty: false`.
- CPU: Intel(R) Core(TM) i7-14700F; 28 logical CPUs; all 28 CPUs in process affinity.
- Physical memory: 33,461,723,136 bytes. CPU-zero governor: `powersave`.
- Storage: Samsung SSD 990 PRO 2TB; benchmark temporary files on Btrfs with zstd level 3 compression.
- No CPU pinning, frequency override, or host-load isolation. No test/build job ran concurrently with this capture.
- OS: `Linux-7.1.9-arch1-2-x86_64-with-glibc2.44`. CPython 3.14.2, SQLite 3.50.4.
- MariaDB 12.3.2, owned loopback TCP server. Redo flush at commit = 1; binary logging off; sync_binlog = 0; InnoDB page size 16384.
- SQLite file-backed WAL, NORMAL synchronization, 5000 ms busy timeout. Compare adapters within each backend, not unlike backend durability policies.
- Package versions: snekql 0.7.0, aiosqlite 0.22.1, aiomysql 0.3.2, sqlalchemy 2.0.54, greenlet 3.5.6, pydantic 2.13.5, anyio 4.14.2.
- Capacity one for every adapter. Contention uses eight workers; other cases use one.

## Primary timing runs

Six rounds per case, with each adapter in each run position twice. Values below
are medians across trials; throughput brackets show the minimum and maximum.
Latency is the median of per-trial p99 values. Loop delay is the median of
per-trial maximum heartbeat lateness. See [measurement definitions](comparison.md).

| Case | Rows | Operations per trial | Warmup | Batch |
| --- | ---: | ---: | ---: | ---: |
| Point / contention / join | 2000 | 2000 | 200 | one row |
| Stream | 20000 | 5 complete scans | 1 | 256 |
| Bulk | separate write table | 100 verified inserts | 10 | 64 rows |

| Backend | Case | Adapter | Ops/s median [min, max] | p99 ms | Max loop delay ms |
| --- | --- | --- | ---: | ---: | ---: |
| sqlite | point | raw | 13567.3 [12438.4, 14757.7] | 0.130 | 0.025 |
| sqlite | point | snekql | 3308.2 [3154.9, 3554.7] | 0.544 | 0.153 |
| sqlite | point | sqlalchemy | 3534.6 [3458.9, 3570.7] | 0.518 | 0.108 |
| sqlite | contention | raw | 13309.6 [10245.3, 13864.3] | 1.176 | 0.023 |
| sqlite | contention | snekql | 2394.7 [2037.9, 2430.6] | 6.178 | 0.198 |
| sqlite | contention | sqlalchemy | 3261.0 [2677.8, 3489.9] | 4.673 | 0.150 |
| sqlite | join | raw | 13444.0 [13173.4, 14441.0] | 0.160 | 0.025 |
| sqlite | join | snekql | 3053.3 [2954.0, 3209.8] | 0.570 | 0.170 |
| sqlite | join | sqlalchemy | 3027.2 [2701.5, 3134.7] | 0.623 | 0.146 |
| sqlite | stream | raw | 40.0 [27.9, 40.9] | 25.400 | 0.339 |
| sqlite | stream | snekql | 3.0 [2.9, 3.0] | 342.586 | 4.824 |
| sqlite | stream | sqlalchemy | 23.6 [22.1, 24.1] | 43.036 | 0.535 |
| sqlite | bulk | raw | 2379.0 [1986.7, 3598.8] | 0.734 | 0.095 |
| sqlite | bulk | snekql | 460.0 [392.1, 558.4] | 3.088 | 1.088 |
| sqlite | bulk | sqlalchemy | 562.7 [376.2, 596.4] | 2.518 | 0.980 |
| mariadb | point | raw | 12235.4 [11777.9, 12495.1] | 0.131 | 0.044 |
| mariadb | point | snekql | 3283.6 [3160.7, 3309.5] | 0.417 | 0.147 |
| mariadb | point | sqlalchemy | 3328.9 [3191.9, 3451.8] | 0.382 | 0.184 |
| mariadb | contention | raw | 11682.0 [10968.3, 12033.2] | 0.922 | 0.052 |
| mariadb | contention | snekql | 2334.0 [2293.4, 2377.0] | 4.230 | 0.154 |
| mariadb | contention | sqlalchemy | 3213.5 [3080.9, 3286.1] | 3.290 | 0.230 |
| mariadb | join | raw | 10919.7 [9983.4, 11754.6] | 0.197 | 0.054 |
| mariadb | join | snekql | 2903.8 [2870.6, 2957.4] | 0.552 | 0.167 |
| mariadb | join | sqlalchemy | 2991.8 [2904.2, 3020.0] | 0.483 | 0.206 |
| mariadb | stream | raw | 18.4 [17.9, 18.6] | 54.768 | 2.054 |
| mariadb | stream | snekql | 4.0 [3.9, 4.0] | 252.211 | 8.804 |
| mariadb | stream | sqlalchemy | 14.1 [13.9, 14.2] | 71.511 | 2.536 |
| mariadb | bulk | raw | 175.2 [138.1, 177.0] | 6.607 | 1.031 |
| mariadb | bulk | snekql | 136.7 [131.7, 142.7] | 9.314 | 1.065 |
| mariadb | bulk | sqlalchemy | 138.9 [137.0, 141.6] | 8.460 | 1.102 |

The raw-driver baseline has the highest median throughput in every captured
case. Snekql and Core are close in several MariaDB cases, but these short runs
do not establish a stable ranking when their trial ranges overlap.
Snekql streaming, especially SQLite streaming, is substantially slower here
even though all adapters perform strict result validation. The benchmark does
not identify which internal cost accounts for the gap; profiling is a separate
investigation, not grounds to remove validation or buffering guarantees.

## Acquisition diagnostics

Three rounds, 1000 operations, 100 warmup, eight workers, capacity one. These
runs enable extra instrumentation and are not primary throughput comparisons.
Core checkout includes more work than raw/snekql admission wait.

| Backend | Adapter | Interval | Median per-trial p99 ms |
| --- | --- | --- | ---: |
| sqlite | raw | admission_wait | 0.628 |
| sqlite | snekql | admission_wait | 6.154 |
| sqlite | sqlalchemy | checkout | 4.008 |
| mariadb | raw | admission_wait | 0.769 |
| mariadb | snekql | admission_wait | 4.080 |
| mariadb | sqlalchemy | checkout | 3.722 |

## Scoped Python allocation profiles

Three rounds per case. Point/join use 200 operations and 50 warmup; streaming
uses three scans of 20000 rows and one warmup; bulk uses 30 inserts of 64 rows
and three warmup. Values are median traced peak KiB for that measurement window.
This includes correctness and instrumentation allocations, excludes pre-existing
objects, and is not total or native peak memory. Raw resident before/after
snapshots remain in JSON; allocator retention makes them unsuitable as a leak verdict.

| Backend | Case | Raw KiB | Snekql KiB | Core KiB |
| --- | --- | ---: | ---: | ---: |
| sqlite | point | 34.8 | 62.2 | 73.4 |
| sqlite | join | 43.8 | 64.1 | 75.7 |
| sqlite | stream | 138.1 | 404.6 | 212.1 |
| sqlite | bulk | 101.6 | 116.3 | 179.4 |
| mariadb | point | 273.3 | 302.6 | 313.1 |
| mariadb | join | 282.3 | 302.9 | 315.1 |
| mariadb | stream | 722.2 | 850.2 | 761.1 |
| mariadb | bulk | 326.8 | 351.4 | 431.0 |

## Reproduction

Use a clean worktree at the recorded runner revision and install the native
MariaDB tools. Follow the private-TMPDIR/environment setup in
[comparison.md](comparison.md). `manifest.json` contains the exact argv for
each report. Run entries sequentially; do not mix a validation suite into the
measurement workload. Keep exit status and stderr, and stop on any failure.

Current source also accepts those commands. If its behavior or dependencies
differ from the recorded revision, treat the output as a new measurement, not
a reproduction of these numbers.

## Regression review without throughput gates

Correctness tests run in CI. Throughput, latency, heartbeat and memory values do
not decide whether CI passes. A failed operation or policy check remains a
failure, never a successful average over the remaining trials.

For a proposed runtime change:

1. Use the same machine, interpreter, native server release, dependency lock,
   storage, settings, profile and workload dimensions. Check the saved metadata;
   do not compare a Core checkout interval to a snekql admission interval or a
   memory-profile latency to a timing-profile latency.
2. Make both source revisions identifiable. Keep background load and power policy
   stable. Record any CPU pinning or governor changes rather than assuming the
   runner did them. Avoid running tests/builds alongside measurements.
3. Run baseline/candidate/baseline, then repeat with reversed order. Use at least
   six rounds per run so every adapter occupies every position twice. Internal
   adapter rotation controls fixed position bias, not drift between revisions.
4. Keep individual trial summaries. Compare medians and ranges across trials;
   use paired whole-trial ratios or differences when configurations and round
   ordering match. Thousands of operations in one trial are correlated samples,
   not thousands of independent experiments. Bootstrap uncertainty across
   independent repeated trials/runs, not individual operations.
5. Treat changes comparable to baseline variation, order effects or disagreement
   between bracketing baselines as inconclusive. Run longer and repeat. A stable
   regression requires a repeatable direction larger than the observed noise,
   not a universal fixed percentage threshold.
6. Review tail latency, loop stalls and allocation changes alongside throughput.
   A speedup obtained by omitting validation, altering buffering, weakening
   durability or leaving work unfinished is a contract change, not a win.

Short scan trials may have only a handful of heartbeat samples. Their p99 values
are descriptive interpolation, not a precise tail estimate. RSS before/after
snapshots are not native peak-memory or leak measurements. Use a separate native
memory profiler when that question matters, and keep its timings out of the
primary comparison.
