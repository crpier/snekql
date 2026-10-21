# Performance investigation — 2026-10-21

## Outcome

The strongest measured optimization target is **projection decoding**, not
Pydantic validation. Two structural protocol checks run for every ordinary
column value. Secondary targets are repeated temporal annotation classification
on writes and generic immutable builder copying/repeated metadata checks.

Follow-up issues, in recommended order:

1. #479: avoid per-value structural protocol checks in projection decoding.
2. #480: resolve temporal classification once rather than per encoded value.
3. #481: reduce immutable builder copying and repeated model metadata checks.

This PR records an investigation, not an implemented optimization. No production
code, tests, dependencies or validation policies changed. No candidate speedup
has been established. The local TDD skill requires confirmation of public test
boundaries before adding regression tests; proposed boundaries are below and in
the issues.

## Method and environment

- Clean baseline: `cb4db57a18f44be1d2e76ad815c214095bf10f6f`, snekql 0.9.0.
- CPython 3.15.0; Pydantic 2.14.0; anyio 4.15.1; aiosqlite 0.22.1;
  aiomysql 0.3.2; SQLAlchemy 2.1.1; greenlet 3.5.6.
- Intel i7-14700F, 28 logical CPUs in affinity, approximately 33.45 GB RAM;
  CPU-zero governor `powersave`; Linux 7.2.8-9-omarchy.
- SQLite 3.53.1, file-backed WAL/NORMAL; MariaDB 13.0.2, privately owned
  loopback server, redo flush policy 1, binary logging off, sync_binlog 0.
- **Temporary databases were on `/tmp` (tmpfs)**, not durable disk. In
  particular, bulk results are not disk-fsync performance estimates. Do not
  compare them with the September Btrfs baseline as a version regression.
- No CPU pinning, frequency override or background-load isolation. This agent
  ran measurements sequentially and only started validation afterward. Host-wide
  background activity was not measured or controlled.
- Every primary run used six trials with rotating adapter order. Ten primary
  runs cover both backends, point reads, indexed joins, complete streaming scans,
  verified bulk writes, and eight-worker contention at pool capacity one.
- Two separate streaming memory runs used three trials. Their instrumented
  timings are **not** primary performance results.

All 12 comparative commands exited successfully with empty stderr. Each performs
value/order/cardinality checks as described in [comparison.md](comparison.md).
Raw individual trials, metadata, and exact effective command arguments are in
[`results/2026-10-21/`](results/2026-10-21/), with `manifest.json` as the index.
For a repeat, create a fresh private temporary directory and use its path for
`TMPDIR`; do not reuse the historical path blindly.

| Case | Rows | Operations/trial | Warmup | Batch | Workers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Point / join | 2000 | 1000 | 100 | 64 (unused) | 1 |
| Stream | 20000 | 5 full scans | 1 | 256 | 1 |
| Bulk | separate write table | 50 verified writes | 5 | 64 | 1 |
| Contention | 2000 | 2000 | 200 | 256 (unused) | 8 |
| Stream memory | 20000 | 3 full scans | 1 | 256 | 1 |

## Primary results

Throughput is median [minimum, maximum] across six trials. p99 is the median
of trial p99 latencies; loop delay is the median of trial maximum heartbeat
lateness. A streaming operation is an entire scan, not one row. A bulk operation
includes insertion, acknowledged commit, and validated readback in a second
transaction. Neither measures only the inner driver call.

| Backend | Case | Adapter | Ops/s median [min, max] | p99 ms | Max loop delay ms |
| --- | --- | --- | ---: | ---: | ---: |
| sqlite | point-read | raw | 13324.0 [10274.9, 15011.0] | 0.168 | 0.030 |
| sqlite | point-read | snekql | 2688.3 [2281.3, 2895.5] | 0.682 | 0.184 |
| sqlite | point-read | sqlalchemy | 3042.6 [2447.0, 3439.9] | 0.664 | 0.138 |
| sqlite | join | raw | 13553.1 [10343.2, 14786.2] | 0.167 | 0.031 |
| sqlite | join | snekql | 2417.9 [2119.9, 2488.2] | 0.778 | 0.212 |
| sqlite | join | sqlalchemy | 2958.6 [2607.5, 3197.6] | 0.658 | 0.131 |
| sqlite | stream | raw | 38.8 [36.1, 39.4] | 26.668 | 0.491 |
| sqlite | stream | snekql | 2.1 [2.0, 2.1] | 487.406 | 4.088 |
| sqlite | stream | sqlalchemy | 19.8 [14.1, 20.4] | 51.406 | 0.672 |
| sqlite | bulk | raw | 2263.4 [1807.0, 3561.9] | 0.604 | 0.062 |
| sqlite | bulk | snekql | 256.0 [212.2, 360.4] | 5.166 | 2.317 |
| sqlite | bulk | sqlalchemy | 471.7 [308.0, 530.7] | 3.410 | 0.884 |
| sqlite | contention | raw | 13179.5 [10780.4, 13676.0] | 1.367 | 0.025 |
| sqlite | contention | snekql | 2161.7 [1855.5, 2279.5] | 6.184 | 0.307 |
| sqlite | contention | sqlalchemy | 2999.8 [2895.9, 3230.1] | 5.059 | 0.135 |
| mariadb | point-read | raw | 12702.9 [11911.0, 13209.0] | 0.127 | 0.040 |
| mariadb | point-read | snekql | 2588.3 [2427.2, 2654.3] | 0.669 | 0.184 |
| mariadb | point-read | sqlalchemy | 3248.9 [3131.6, 3303.2] | 0.606 | 0.212 |
| mariadb | join | raw | 11350.7 [9460.7, 12517.8] | 0.204 | 0.052 |
| mariadb | join | snekql | 2282.3 [2173.1, 2296.8] | 0.565 | 0.207 |
| mariadb | join | sqlalchemy | 2941.5 [2797.5, 2983.6] | 0.532 | 0.191 |
| mariadb | stream | raw | 21.4 [21.0, 21.6] | 47.133 | 1.746 |
| mariadb | stream | snekql | 2.7 [2.6, 2.7] | 378.576 | 14.658 |
| mariadb | stream | sqlalchemy | 14.2 [14.1, 14.4] | 70.548 | 2.623 |
| mariadb | bulk | raw | 1894.0 [1314.3, 2059.9] | 0.624 | 0.181 |
| mariadb | bulk | snekql | 328.7 [315.4, 331.2] | 3.296 | 1.320 |
| mariadb | bulk | sqlalchemy | 483.5 [477.0, 488.9] | 2.320 | 1.217 |
| mariadb | contention | raw | 12443.6 [11459.6, 12555.4] | 1.023 | 0.041 |
| mariadb | contention | snekql | 2272.7 [2239.8, 2287.4] | 4.865 | 0.358 |
| mariadb | contention | sqlalchemy | 3120.6 [2743.0, 3229.0] | 3.221 | 0.199 |

The streaming gap is large and consistent across trials on both backends.
Some smaller point-read differences overlap trial ranges: don't assign a stable
ranking based solely on their medians. Raw drivers do not provide all snekql's
lifecycle guarantees. These results do not justify dropping deadlines, fairness,
validation, reset policy, or transaction boundaries.

### Streaming allocation profile

Median incremental traced Python peak, KiB, three trials:

| Backend | raw | snekql | SQLAlchemy |
| --- | ---: | ---: | ---: |
| SQLite | 137.6 | 404.1 | 210.7 |
| MariaDB | 685.4 | 818.4 | 724.4 |

This includes worker/measurement allocations but excludes setup and pre-existing
allocations. It is neither total memory nor native peak RSS nor evidence of a
leak. Batch size was 256; reports retain observed batch/row counts.

## Profile findings

Profiles are separate diagnostic runs, never inputs to the throughput table.
Python profiling disproportionately penalizes Python call-heavy paths and async
cumulative times can be misleading. Treat call counts and source inspection as
localization evidence, not a prediction of achievable speedup.

### 1. Projection dispatch (#479)

`snekql/_value_decode.py:_decode_selectable` checks `PolicySelectable` and
`DialectSelectable` before `Attr`. A 10-scan + one-warmup profile has 660,000
selectable decode calls (220,000 rows x three columns), and 1,320,134 structural
protocol instance checks. Instrumented cumulative time:

- `typing.__instancecheck__`: 7.377 seconds;
- `Attr.decode`: 0.889 seconds;
- `_decode_selectable`: 9.524 seconds, including its callees.

These are nested times, not additive categories. The same path dominates verified
bulk readback. Most checks are negative tests for ordinary columns.

Candidate: concrete-column dispatch before structural protocols, or resolve the
value decoder once per execution plan. Before reordering, verify whether Attr
subclasses can also implement a protocol and whether precedence is contractual.
Keep dialect leaves, policy-aware expressions, scalar subqueries, aggregates,
LEFT JOIN null extension and RETURNING semantics. Never simply disable validation.

### 2. Temporal classification on ordinary writes (#480)

`snekql/storage.py:_encode_value` invokes `_temporal_type` even for non-temporal
integer/text values. The bulk profile (1,000 operations + 100 warmup, 64-row
batches) has 213,416 classification calls, taking 0.996 seconds cumulatively
under profiling, inside 1.660 seconds of `_encode_value` time. This repeatedly
resolves annotations and walks logical types to recover immutable declaration
facts. Candidate: finalize/cache classification, **including negative results**,
after binding. Forward references, subclass identity and lazy declaration
resolution determine the safe cache lifetime. Preserve temporal compatibility,
precision and exact-write rejection.

### 3. Builder copying and repeated metadata validation (#481)

Unprofiled `uv run python -m benchmarks.construction`, 15 x 50,000 builds after
5,000 warmup per workload:

| Workload | Median builds/s | CV | Retained bytes/query |
| --- | ---: | ---: | ---: |
| point_read | 92,202 | 0.20% | 521.6 |
| filtered | 42,654 | 0.17% | 769.5 |
| projection | 74,001 | 0.15% | 506.8 |
| insert | 250,709 | 0.11% | 473.2 |
| update | 132,970 | 0.55% | 522.2 |

Separate 20,000-build profiles show five `dataclasses.replace` calls per filtered
chain (0.511 seconds cumulative), nine `require_model_columns` calls per filtered
chain (0.206 seconds), and seven per point-read chain. Candidate: specialized
immutable state copies and consolidation of redundant binding/owner checks.
Do not trade away query branch independence or dynamic backend/owner rejection.
Do not introduce a global compiled-query cache as a shortcut: parameter identity,
lifetimes and mutable inputs require separate design.

Point-read profiles also show event-loop/driver-operation/lifecycle overhead.
There is no evidence yet that removing any particular lifecycle guard is safe
or that builder speed alone will close the raw-driver gap.

## Reproducing profiles

The readable profile summaries are in `results/2026-10-21/profiles.txt`.
Binary cProfile files are machine-specific and are not checked in. With a fresh
private temporary directory as `TMPDIR` and `PYTHON_CONTEXT_AWARE_WARNINGS=1`:

```sh
uv run python -m cProfile -o /tmp/stream.prof -m benchmarks.compare \
  --backend sqlite --adapter snekql --workload stream \
  --operations 10 --rows 20000 --trials 1 --warmup 1

# Repeat for point-read and bulk (separate output profile files):
uv run python -m cProfile -o /tmp/bulk.prof -m benchmarks.compare \
  --backend sqlite --adapter snekql --workload bulk \
  --operations 1000 --rows 2000 --trials 1 --warmup 100 --batch-size 64
```

Print summaries with `pstats.Stats(path).strip_dirs().sort_stats('tottime').print_stats(35)`.
Construction summaries use a fresh `cProfile.Profile()` around 20,000 calls to
each callable in `benchmarks.construction.WORKLOADS`, then print the top 15
entries sorted by `tottime`. Unlike the primary construction run, these profiles
have no explicit warmup or GC control and are diagnostic only.

## Proposed next unit of work

Start with #479. Confirm these public test boundaries before adding tests:

| Boundary | Catches | Does not establish |
| --- | --- | --- |
| `Transaction.fetch_all` and `fetch_chunks` over typed projections | Values, validation failures, nulls, batching | Private dispatch strategy or machine throughput |
| Public expression projections, including dialect leaves, aggregates, scalar subqueries and LEFT JOIN | Extension semantics and null extension | Arbitrary unsupported private objects |
| Public write RETURNING consumption where supported | Read/write decoder consistency | Unsupported backend capabilities |

Then add missing semantic coverage test-first, implement one focused change,
and use baseline/candidate/baseline plus reversed order with six rotating trials
on **both** backends. Compare tail latency, stalls and allocations as well as
throughput. Follow the noise guidance in [findings.md](findings.md); do not turn
local throughput numbers into CI gates. Expand to disk-backed workloads and
larger/wider row contracts before making broad capacity recommendations.

## Validation of the unchanged baseline

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (530 files).
- `uv run ty check`: passed.
- All 12 comparative benchmark runs: passed their built-in correctness checks.
- Initial full-suite attempts were not usable: the foreground run exceeded the
  tool's three-minute limit; a subsequent attempt encountered MariaDB error 122
  (temporary filesystem quota/preallocation failure).
- Full rerun with `TMPDIR=/home/crpier/.cache/snekql-perf-validation/tmp` and
  `PYTHON_CONTEXT_AWARE_WARNINGS=1`: **3892 passed, 4 errors**, exit status 1,
  1630.81 seconds. All four errors are `TimeoutError` at line 109 in
  `tests/testing/mariadb/test_password_literals.py`, the four parameter cases of
  `cli_environment_password_authenticates` (ordinary/NO_BACKSLASH_ESCAPES x
  root/worker). No library or test code had been changed. This is **not** a green
  full-suite result; the timeout cause has not been diagnosed by this
  performance investigation.

The full rerun log remains locally at
`/home/crpier/.cache/snekql-perf-validation/tests.log`. Validation ran after the
benchmark captures and must not be interpreted as a profiled workload.
