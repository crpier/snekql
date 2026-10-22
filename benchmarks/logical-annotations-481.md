# Resolved logical annotations — #481

Measured 2026-10-21 against clean baseline `a10cd17` and candidate `f84e6a7`.
Both include #485/#486; **neither includes unmerged #489 or #490**. The results
are independent, not measurements of their combined gains.

## Change

Retain a fully resolved logical annotation per column instead of repeatedly
extracting it from the model hint and stripping its field-level JSON marker.
Ordering, numeric-aggregate and native-expression gates still run; they inspect
the same type object as before. Validation, nullability, bool/integer distinction,
storage compatibility and ownership/backend checks are not removed.

Unbound columns, unresolved forward references and resolution failures remain
uncached. This matters when a module-level name becomes a ZonedDatetime after an
earlier permissive ordering attempt. The private cache may populate after column
metadata freezes. Aliases keep their source annotation and may copy its resolved
type. Overridable methods are still called normally; no global/type-wide cache.

A separate source-normalization experiment was shelved as unproven. Its noisy
exploratory timings are **not** included here, and none of that code is included.

## Construction results

Six fresh process phases, **B/C/B then C/B/C**. Each workload runs six trials of
50,000 builds after 5,000 warmup calls, with GC disabled during timing. Medians
below contain 18 samples per revision/workload. SQL and parameters were captured
outside timing and agree across all six processes.

| Workload | Baseline builds/s | Candidate builds/s | Ratio |
| --- | ---: | ---: | ---: |
| Point read (equality + limit; control) | 92,139 | 92,124 | 1.00× |
| Filtered chain (range + ordering) | 42,882 | 46,024 | 1.07× |
| Projection with range predicate | 74,629 | 77,636 | 1.04× |
| Insert (control) | 254,363 | 253,292 | 1.00× |
| Update (equality; control) | 129,071 | 128,295 | 0.99× |
| Numeric aggregate | 97,816 | 107,336 | 1.10× |
| Native numeric expression | 165,315 | 193,702 | 1.17× |
| Whole-model selection + ordering | 113,312 | 125,712 | 1.11× |

These are **warm-column construction** gains, not execution gains or an estimate
of first model-declaration cost. Equality-only controls do not exercise the new
cache in their builder paths and remain approximately unchanged.

Separate profiling of 20,000 filtered builds:

| Function | Baseline calls / cumulative s | Candidate calls / cumulative s |
| --- | ---: | ---: |
| `_resolved_logical_type` | 40,000 / 0.208 | 40,000 / 0.004 |
| `_require_ordering` | 40,000 / 0.286 | 40,000 / 0.084 |
| `_resolve_model_hint` | 40,000 / 0.030 | 0 / — |
| `require_model_columns` | 180,000 / 0.207 | 180,000 / 0.205 |

The type-resolution and ordering methods still run; only repeated resolution is
avoided. Profile times are nested and instrumented, not additive or throughput
estimates. Model-column checks remain unchanged.

## Memory and runtime controls

Separate tracemalloc snapshot differences, 5,000 retained builds and three
samples per workload/revision. Median bytes per build, including list overhead:

| Retained output | Baseline bytes | Candidate bytes |
| --- | ---: | ---: |
| Finished point-read query | 528 | 523 |
| Finished filtered query | 773 | 772 |
| Finished projection | 511 | 513 |
| Insert | 475 | 475 |
| Update | 525 | 523 |
| Numeric aggregate | 506 | 505 |
| Numeric expression | 580 | 577 |
| Ordered whole-model query | 516 | 515 |
| Base + two paginated branches | 1,155 | 1,155 |
| All six intermediate filtered-chain stages | 2,326 | 2,323 |

Retained **query** memory is approximately unchanged. The implementation adds a
small private cache slot and a tuple per resolved column, lasting as long as that
descriptor. Model-declaration/setup allocations are excluded from these snapshots,
so this does **not** establish zero added memory. It does not measure total/native
RSS or transient allocation rate.

Point-read runtime controls used 2,000 seeded rows, 500 operations/trial, 50 warmup
and six rotating raw/snekql/SQLAlchemy trials per invocation. Backend order
alternated by phase; medians contain 18 samples per adapter/revision:

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 12,486 | 13,929 |
| SQLite | snekql | 2,843 | 2,848 |
| SQLite | SQLAlchemy | 3,259 | 3,095 |
| MariaDB | raw | 11,684 | 12,514 |
| MariaDB | snekql | 2,532 | 2,514 |
| MariaDB | SQLAlchemy | 3,092 | 3,113 |

**No runtime speedup is claimed.** This equality-only workload is a negative
control, not a workload demonstrating the new cache's benefit; controls also move.
Median snekql trial p99 latency: SQLite 0.612 → 0.607 ms; MariaDB 0.700 → 0.700 ms.
Median trial maximum heartbeat lateness: SQLite 0.160 → 0.118 ms; MariaDB
0.187 → 0.202 ms. Those noisy observations are not attributed to the cache.

## Evidence and validation

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6. Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, powersave governor;
no pinning or host-wide load isolation. Private Btrfs disk-backed databases,
SQLite WAL/NORMAL, MariaDB redo flush policy 1 and binary logging off.

Retained measurements ran sequentially, with profiling/memory separate. The
runner checked for other Python snektest/pytest runners before each command and
waited when one was visible. This is not exclusive host ownership and cannot
prevent another process starting mid-command. Our full suite started only after
all measurement commands completed.

[Construction metadata](results/logical-annotations-481/construction-manifest.json),
[288 timing samples](results/logical-annotations-481/construction-trials.csv), and
[60 memory samples](results/logical-annotations-481/memory-trials.csv) retain source
revisions, selected worktree paths, interpreter, compiled output and parameters.
The [runtime manifest](results/logical-annotations-481/manifest.json) and
[216 runtime trials](results/logical-annotations-481/trials.csv) retain all twelve
point-read reports with environment/session policies. CSV `run` joins report
metadata; empty optional values are null and lists remain JSON inside cells.
All retained commands exit zero with empty stderr. Raw reports, scripts, profiles
and logs remain in `/home/crpier/.cache/snekql-481-logical/`.

Three public-interface tests protect late ZonedDatetime resolution, independent
numeric/bool/JSON domains, constrained writes, aliased arithmetic and nullable
aggregate results. They pass on the baseline. A premature forward-reference cache
fails the late-annotation case, as does prohibiting cache population after metadata
freezes; both incorrect variants were reverted. Focused query/temporal/binding
tests: **702 passed**; separate SQLite/MariaDB JSON tests: **36 passed**. An initial
focused command named a nonexistent JSON file and was corrected; only completed
runs are counted. Full-suite and final CI/static status are in the implementation PR.

## Reproduction

Use the same interpreter/dependencies and a private disk-backed `TMPDIR`, with
`PYTHON_CONTEXT_AWARE_WARNINGS=1`:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload point-read \
  --rows 2000 --operations 500 --trials 6 --warmup 50
# Repeat with --backend mariadb; interleave revisions as above.
```

Save this script outside the source trees and execute from each clean worktree
with `timing`, then separately `memory` and `profile OUTPUT.prof`. Source-path
insertion prevents a shared editable installation selecting the other checkout.

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


WORKLOADS = dict(
    WORKLOADS,
    numeric_aggregate=lambda: sqlite.select(BenchUser.age.sum()),
    numeric_expression=lambda: sqlite.select(BenchUser.age.add(1)),
    ordering=lambda: sqlite.select(BenchUser).order_by(BenchUser.id.asc()),
)


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
