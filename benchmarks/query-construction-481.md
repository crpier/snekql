# Immutable query construction — #481

Measured 2026-10-21 against clean baseline `a10cd17` (both #485 and #486 merged)
and clean candidate `fa8be17`. This measures an additional improvement on top of
those two changes, not a comparison against the original pre-optimization tree.

## Change and scope

The four private query-state records have only ordinary constructor fields.
Fluent builders now copy their existing field dictionary into a fresh mapping,
apply changes there, and run the normal constructor. This avoids generic
`dataclasses.replace` field discovery without bypassing construction or manually
maintaining a second list of state fields. State subclasses retain the generic
path for slots, InitVars and non-init fields. Non-state dataclasses are unchanged.

This addresses the **state-copy portion** of #481. Model-column checks, backend
checks, ownership checks, forward binding and query-readiness guards are unchanged.
There is no mutable builder, compiled-query cache or global model-metadata cache.
Reducing redundant metadata checks remains a separate opportunity under #481.

## Construction throughput

Existing `benchmarks.construction` workloads, 5,000 warmup builds and six trials
of 50,000 builds per invocation. GC is disabled only during timing. Six clean
process phases in **B/C/B then C/B/C** order give 18 samples per workload/revision.
The five workloads run in the same order in each process. Compiled SQL and
parameters were captured outside timing and agree across all six invocations.

| Workload | Baseline builds/s | Candidate builds/s | Ratio |
| --- | ---: | ---: | ---: |
| Point read | 93,366 | 107,418 | 1.15× |
| Filtered chain | 43,077 | 52,324 | 1.21× |
| Projection | 74,145 | 85,776 | 1.16× |
| Insert | 250,379 | 253,504 | 1.01× |
| Update | 127,653 | 150,085 | 1.18× |

These are medians of **construction**, not SQL execution throughput. A bare insert
constructs its initial state without copying; its approximately 1% change is not
claimed as an optimization benefit.

A separate warmed cProfile run of 20,000 filtered builds shows 100,000 generic
`dataclasses.replace` calls (0.513 s instrumented cumulative) replaced by 100,000
specialized copies (0.198 s). **180,000 `require_model_columns` calls remain** in
both revisions (0.209 / 0.202 s). Profile times are nested/instrumented, not
additive or substitutes for the uninstrumented timing results.

## Memory tradeoff

Separate `tracemalloc` snapshot differences, holding 5,000 builds alive, three
samples per workload/revision. Medians below are retained bytes per build,
including the retaining-list overhead; they are not total RSS or allocation rate.

| Retained output | Baseline bytes | Candidate bytes |
| --- | ---: | ---: |
| Finished point-read query | 524 | 525 |
| Finished filtered query | 774 | 776 |
| Finished projection | 512 | 512 |
| Finished insert | 475 | 475 |
| Finished update | 527 | 522 |
| Base + two independently paginated branches | 1,155 | 1,222 |
| All six intermediate stages of a filtered chain | 2,325 | 2,643 |

**Retaining intermediate builders costs more memory.** Reading `vars(state)`
materializes the source instance dictionary; it does not mutate its field values.
A retained base-and-branches bundle adds approximately 67 bytes (+5.8%); retaining
all six stages adds approximately 318 bytes (+13.7%). Finished-query retained
memory is approximately unchanged because discarded intermediates are released.
This is a CPU/memory tradeoff, not an allocation-reduction claim. Applications
retaining many intermediate query objects should consider this cost.

## End-to-end point reads: modest, noisy observations

Both backends, 2,000 seeded rows, 500 operations per trial, 50 warmup, six rotating
raw/snekql/SQLAlchemy trials per invocation; 18 trials per adapter/revision.
Backend order alternates between phases. Each operation includes the existing
harness's transaction and result verification, not just query construction.

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 11,561 | 12,696 |
| SQLite | snekql | 2,603 | 2,792 |
| SQLite | SQLAlchemy | 2,907 | 2,937 |
| MariaDB | raw | 12,467 | 12,676 |
| MariaDB | snekql | 2,478 | 2,536 |
| MariaDB | SQLAlchemy | 3,057 | 3,141 |

Observed snekql ratios are 1.07× / 1.02×, but controls also move (SQLite raw rises
approximately 10%). **Do not claim these as isolated end-to-end gains from state
copying.** Construction improves clearly; driver/transaction scheduling and host
variation still dominate this small point-read difference.

Median snekql trial p99 latency: SQLite 0.686 → 0.626 ms; MariaDB 0.720 → 0.775 ms.
Median trial maximum heartbeat lateness: SQLite 0.168 → 0.155 ms; MariaDB
0.188 → 0.197 ms. Thus latency does not improve uniformly across backends.

## Environment and evidence

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6. Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, `powersave` governor,
no CPU pinning or host-wide load control. Private disk-backed Btrfs databases;
SQLite WAL/NORMAL and MariaDB redo flush policy 1 with binary logging off.
All retained local measurements ran sequentially, before our full test suite;
no tests were launched alongside them. Memory and profiling are separate runs.

[Construction metadata](results/query-construction-481/construction-manifest.json),
[180 timing samples](results/query-construction-481/construction-trials.csv), and
[42 memory samples](results/query-construction-481/memory-trials.csv) retain source
revisions, interpreter, compiled query output and measurement parameters.
The [runtime manifest](results/query-construction-481/manifest.json) and
[216 runtime trials](results/query-construction-481/trials.csv) retain all twelve
point-read reports, commands, environment and session policies. `run` joins CSV
rows to report metadata; optional empty CSV values are null and lists are JSON.
All measurement commands exited zero with empty stderr. Raw reports, preliminary
experiments, profiles, mutation logs and scripts remain in
`/home/crpier/.cache/snekql-481/`.

Five public regression tests cover independent pagination, grouped named results,
HAVING, read/write execution, write readiness, conflict/RETURNING branching, and
foreign-owner/backend rejection. They also pass on the unmodified baseline.
Deliberately mutating source SELECT/UPDATE state fails the branching/readiness
tests; deliberately dropping HAVING fails the grouped-result test. Those variants
were reverted. No private copy-call assertions or timing thresholds enter CI.
Focused validation: **743 passed**. Full-suite and final static-check results are
recorded in the implementation PR.

## Reproduction

Use the same interpreter and dependencies in each clean worktree, with a private
Btrfs `TMPDIR` and `PYTHON_CONTEXT_AWARE_WARNINGS=1`. Runtime invocation:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload point-read \
  --rows 2000 --operations 500 --trials 6 --warmup 50
# Repeat with --backend mariadb; interleave baseline and candidate as above.
```

Save the following script **outside** the source trees. Run from each worktree
with `timing`, then separately `memory` and `profile OUTPUT.prof`. It inserts the
selected worktree before imports so an editable installation pointing at another
checkout cannot silently select the wrong code.

```python
import cProfile
import dataclasses
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
from benchmarks.construction import (
    WORKLOADS,
    BenchUser,
    measure_memory,
    measure_throughput,
)
from snekql import sqlite
import snekql._query_state


def branches():
    base = sqlite.select(BenchUser).where(BenchUser.age.gt(18))
    return base, base.limit(1), base.offset(1).limit(2)


def retained_chain():
    root = sqlite.select(BenchUser)
    filtered = root.where(BenchUser.age.gt(18))
    named = filtered.where(BenchUser.name.eq("alice"))
    ordered = named.order_by(BenchUser.id.desc())
    limited = ordered.limit(10)
    offset = limited.offset(5)
    return root, filtered, named, ordered, limited, offset


mode = sys.argv[1]
report = dict(
    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
    python=sys.version,
    source=snekql._query_state.__file__,
    mode=mode,
    samples=[],
)
if mode == "timing":
    report["warmup"] = 5000
    report["compiled"] = {}
    for name, op in WORKLOADS.items():
        compiled = op().compile()
        report["compiled"][name] = dict(
            sql=compiled.sql, params=compiled.params, backend=compiled.backend
        )
        result = measure_throughput(
            name, op, ops_per_trial=50000, trials=6, warmup=5000
        )
        report["samples"].append(dataclasses.asdict(result))
elif mode == "memory":
    report["count"] = 5000
    for trial in range(3):
        for name, op in dict(
            WORKLOADS, branches=branches, retained_chain=retained_chain
        ).items():
            report["samples"].append(
                dict(
                    workload=name,
                    trial=trial + 1,
                    retained_bytes_per_build=measure_memory(op, count=5000),
                )
            )
elif mode == "profile":
    for _ in range(5000):
        WORKLOADS["filtered"]()
    profile = cProfile.Profile()
    profile.enable()
    for _ in range(20000):
        WORKLOADS["filtered"]()
    profile.disable()
    profile.dump_stats(sys.argv[2])
else:
    raise ValueError(mode)
print(json.dumps(report))
```
