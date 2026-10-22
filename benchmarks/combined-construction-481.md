# Combined construction improvements — #481

Measured 2026-10-22: clean `a10cd17` → clean `84e6f0d`. The baseline already
contains #485/#486. The candidate additionally contains **#489, #490, #492 and
#493 together**. These are actual combined measurements, not products of their
independent results. No #494 implementation is included.

## Construction and retained memory

Sequential B/C/B then C/B/C, six trials of 50,000 builds per case/process, 5,000
warmups, GC disabled during timing. Each median has 18 samples per revision.
SQL/parameters agree across all six processes. SQLite builders exercise shared
query machinery; no I/O or compilation is timed in this table.

| Workload | Baseline builds/s | Combined builds/s | Ratio |
| --- | ---: | ---: | ---: |
| Point read | 91,892 | 137,396 | 1.50× |
| Filtered chain | 42,663 | 66,288 | 1.55× |
| Projection | 74,487 | 96,516 | 1.30× |
| Insert control | 252,419 | 251,141 | 0.99× |
| Update | 132,564 | 151,363 | 1.14× |
| Numeric aggregate | 98,070 | 107,955 | 1.10× |
| Numeric expression | 165,540 | 194,991 | 1.18× |
| Ordered model | 113,302 | 177,040 | 1.56× |
| Keyword point read | 89,474 | 123,203 | 1.38× |
| IntEnum point read | 90,799 | 127,012 | 1.40× |
| Page an existing model builder | 213,258 | 423,105 | 1.98× |
| Page an existing compound builder | 216,465 | 432,470 | 2.00× |

The last two cases time only `limit(10).offset(5)` on a prebuilt base. Keyword and
IntEnum calls do not take #493's shortcut; they benefit from the other changes.

Separate tracemalloc snapshots retained 5,000 outputs, three samples/case/revision.
Median filtered-query retention stays **775 bytes**. Retaining a base and two
branches grows **1,157 → 1,220 bytes**; retaining all six chain stages grows
**2,324 → 2,646 bytes** (about 14%). This preserves #489's disclosed dictionary-
materialization tradeoff. Declaration, import, cache warmup and native memory
are excluded; this is not a total-memory or allocation-rate measurement.

## Execution controls

Private disk-backed point reads: 2,000 rows, 2,000 operations/trial, 200 warmups,
six rotating adapter trials per invocation; backend order alternates by phase.
Median throughput across 18 samples per adapter/revision:

| Backend | Adapter | Baseline ops/s | Combined ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 13,212 | 12,950 |
| SQLite | snekql | 2,764 | 2,710 |
| SQLite | SQLAlchemy | 3,157 | 2,961 |
| MariaDB | raw | 12,663 | 12,723 |
| MariaDB | snekql | 2,566 | 2,599 |
| MariaDB | SQLAlchemy | 3,155 | 3,207 |

**No end-to-end improvement is established.** Construction gains are substantial,
but these transaction-heavy point reads do not establish a corresponding gain.

## Evidence and reproduction

[432 construction trials](results/combined-construction-481/construction-trials.csv),
[84 memory samples](results/combined-construction-481/memory-trials.csv), and
[probe metadata](results/combined-construction-481/probe-manifest.json) retain
revisions, interpreter, plugin discovery, output SQL and settings. The
[runtime manifest](results/combined-construction-481/manifest.json) and
[216 runtime trials](results/combined-construction-481/trials.csv) retain commands,
source/environment, native session policy and all adapter results.

CPython 3.15.0, Pydantic 2.14.0, SQLite 3.53.1, MariaDB 13.0.2; i7-14700F,
28 logical CPUs, powersave governor, no CPU pinning or exclusive host ownership.
SQLite WAL/NORMAL and MariaDB redo-flush policy 1, binary logging off, on private
Btrfs disk-backed data. Each command waits for visible Python test runners;
other sessions can still start work mid-command. Timing, profiles and memory
ran sequentially, before any owned validation suite.

All retained commands exited zero with empty stderr and clean source trees.
An initial probe used unsupported `column + 1` syntax; it was corrected to the
public `column.add(1)` before the retained series. Its failed output is excluded.
Raw evidence and scripts remain in `/home/crpier/.cache/snekql-combined-481/`.

Run the following standalone script from each exact worktree with `timing`, then
separately `memory` or `profile OUTPUT.prof`. Shared dependencies must be identical.
Runtime reproduction uses `python -m benchmarks.compare --backend sqlite
--workload point-read --rows 2000 --operations 2000 --trials 6 --warmup 200`,
and the corresponding MariaDB command. Set a private disk-backed `TMPDIR` and
`PYTHON_CONTEXT_AWARE_WARNINGS=1`.

```python
import cProfile
import dataclasses
import json
import os
from importlib.metadata import entry_points
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


from enum import IntEnum
from pydantic import BaseModel


class One(IntEnum):
    VALUE = 1


class UserId(BaseModel):
    user_id: int


model_base = sqlite.select(BenchUser)
label = BenchUser.id.label("user_id")
left = sqlite.select(BenchUser).project(UserId, user_id=label)
compound_base = left.union_all(left)
WORKLOADS = dict(
    WORKLOADS,
    numeric_aggregate=lambda: sqlite.select(BenchUser.age.sum()),
    numeric_expression=lambda: sqlite.select(BenchUser.age.add(1)),
    ordered_model=lambda: sqlite.select(BenchUser).order_by(BenchUser.age.desc()),
    keyword_point=lambda: (
        sqlite.select(BenchUser).where(BenchUser.id.eq(1)).limit(value=1)
    ),
    subtype_point=lambda: (
        sqlite.select(BenchUser).where(BenchUser.id.eq(1)).limit(One.VALUE)
    ),
    model_page=lambda: model_base.limit(10).offset(5),
    compound_page=lambda: compound_base.limit(10).offset(5),
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
    pydantic_plugins=[e.name for e in entry_points(group="pydantic")],
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
