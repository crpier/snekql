# Projection decoding optimization — #479

Measured 2026-10-21. Baseline `cb4db57a18f44be1d2e76ad815c214095bf10f6f`;
candidate `9b8a0be` (code and regression tests). Both trees were clean during
measurement. This report accompanies the implementation, not a separate
investigation PR.

## Change and scope

Resolve ordinary column decoders once per select execution plan, or once per
explicit RETURNING batch, instead of performing structural protocol dispatch
for each value. Each decoder retains its execution's backend, validation flag,
and LEFT JOIN null-extension policy. There is no global or class-level cache.

Column subclasses implementing policy/dialect projection seams retain their
existing precedence. Non-column expressions and extension columns use the
unchanged general decoder. Whole-model materialization is unchanged. This does
**not** optimize all CTE, aggregate, scalar-subquery or dialect-expression paths;
those retain their existing semantics and dispatch.

## Results

Each cell is the median across 18 trials (three invocations × six rotating
adapter trials). The sequence was **baseline/candidate/baseline**, followed by
**candidate/baseline/candidate**, on both backends. Each invocation includes raw,
snekql and SQLAlchemy controls. Throughput includes the existing benchmark's
correctness checks; streaming units are complete 20,000-row scans, not rows.

| Backend | Workload | Baseline ops/s | Candidate ops/s | Ratio |
| --- | --- | ---: | ---: | ---: |
| SQLite | Stream | 2.664 | 14.232 | 5.34× |
| MariaDB | Stream | 2.027 | 11.308 | 5.58× |
| SQLite | Point read | 2550.9 | 2608.1 | 1.02× |
| MariaDB | Point read | 2514.9 | 2506.3 | 1.00× |
| SQLite | Verified bulk | 303.0 | 455.7 | 1.50× |
| MariaDB | Verified bulk | 114.5 | 137.9 | 1.20× |

Individual six-trial streaming medians in execution order:

| Backend | B1 | C2 | B3 | C4 | B5 | C6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite | 2.55 | 13.04 | 2.60 | 14.57 | 2.72 | 14.01 |
| MariaDB | 2.01 | 11.39 | 2.03 | 11.32 | 2.62 | 11.11 |

The streaming improvement is consistent in both orders. Point-read differences
are small relative to run-to-run variation: do **not** claim a point-read gain.
Bulk operations include committed writes and verified readback, so faster
readback improves that composite workload; these are not insert-only speedups.

Median trial p99 latency / median trial maximum heartbeat lateness, milliseconds:

| Backend | Workload | Baseline p99 | Candidate p99 | Baseline lateness | Candidate lateness |
| --- | --- | ---: | ---: | ---: | ---: |
| SQLite | Stream | 413.020 | 81.522 | 6.972 | 1.313 |
| MariaDB | Stream | 496.762 | 89.107 | 15.645 | 3.307 |
| SQLite | Point read | 0.706 | 0.661 | 0.181 | 0.169 |
| MariaDB | Point read | 0.741 | 0.731 | 0.245 | 0.220 |
| SQLite | Verified bulk | 4.862 | 3.203 | 1.906 | 1.170 |
| MariaDB | Verified bulk | 11.411 | 9.026 | 1.547 | 1.058 |

Separate three-trial streaming memory runs show essentially unchanged
incremental traced Python peak: 404.1 → 400.4 KiB on SQLite and
817.9 → 819.3 KiB on MariaDB. These are allocation diagnostics, not total/native
memory or peak RSS; their timings are excluded from the primary results.

A separate SQLite CPU profile (10 scans + one warmup, batch size 256) confirms
that the intended work was removed, not validation:

| Profile count | Baseline | Candidate |
| --- | ---: | ---: |
| Structural protocol `typing.__instancecheck__` | 1,320,134 | 200 |
| `Attr.decode` | 660,000 | 660,000 |
| Ordinary-column decoder resolution | n/a | 33 |

Profile timings are instrumented and are not used as throughput evidence.

## Reproduction and limitations

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6; Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, `powersave` governor.
No CPU pinning or host-wide background-load control. All benchmark commands ran
sequentially; full-suite validation started only after measurements/profiles.

Unlike the earlier #483 investigation, this comparison uses a **disk-backed
Btrfs temporary directory**, not tmpfs, for both revisions. SQLite uses
WAL/NORMAL; MariaDB has redo flush policy 1 and binary logging off. Do not compare
absolute numbers with #483 or treat these local ratios as universal capacity
estimates. The raw/SQLAlchemy controls and variation are retained in the data.

For each of the six phases, run each workload on each backend, reversing backend
order in alternating phases. Use a fresh private, disk-backed `TMPDIR` and
`PYTHON_CONTEXT_AWARE_WARNINGS=1` for every command:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload stream \
  --rows 20000 --operations 5 --trials 6 --warmup 1 --batch-size 256
uv run python -m benchmarks.compare --backend sqlite --workload point-read \
  --rows 2000 --operations 1000 --trials 6 --warmup 100
uv run python -m benchmarks.compare --backend sqlite --workload bulk \
  --rows 2000 --operations 50 --trials 6 --warmup 5 --batch-size 64
# Repeat with --backend mariadb. Omitted --adapter defaults to rotating all three.
```

For memory, use the streaming command with `--operations 3 --trials 3 --profile
memory`. For CPU profiles, use `python -m cProfile -o PATH -m benchmarks.compare`
with `--adapter snekql --operations 10 --trials 1` and the streaming arguments.

The checked-in [manifest](results/projection-decoding-479/manifest.json) contains
exact original commands, environment snapshots, report headers and session
policies for all 40 successful runs (648 timing + 36 memory trials).
[trials.csv](results/projection-decoding-479/trials.csv) flattens the trial fields;
`run` joins to the manifest and `session_policy` references its policy dictionary.
List fields remain JSON arrays inside CSV cells; empty optional fields are null.
All 40 runs exited successfully with empty stderr and passed built-in
value/order/cardinality checks. Local original JSON and binary profiles remain
under `/home/crpier/.cache/snekql-479/`.

## Semantic regression checks

New tests exercise public buffered/streamed projections and write RETURNING:
policy versus dialect versus ordinary-column precedence, including Attr
subclasses, and validation isolation when reusing a query. All ten assertions
pass on the baseline too: this is a behavior-preserving optimization.

Sensitivity checks deliberately introduced and then reverted unsafe variants:
seven cases fail if the resolver bypasses extension precedence; three fail if
ordinary-column validation is disabled. The initial naive Attr-first reorder
also failed all four initial policy-projection cases. No timing assertions or
private dispatch-call assertions are added to CI.

Existing tests cover named results, LEFT JOIN null extension, scalar subqueries,
aggregates, dialect leaves and backend codecs. Focused validation: **689 passed**.
Full-suite and static-check results are recorded in the implementation PR.
