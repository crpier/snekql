# Whole-model SELECT metadata checks — #481

Measured 2026-10-21 against clean baseline `a10cd17` and clean candidate `8e5cdc4`.
Both include merged #485/#486, but **neither includes #489's state-copy change**.
The final helper was subsequently relocated beside the ownership accessors without
changing its logic. Do not multiply these gains by #489's independently measured gains.

## Scope and safety

A namespace's `select(Model)` already binds/validates the anchor's metadata in
`build_select`, then checks that anchor's backend. Previously it repeated model
and namespace checks for every projected column, even when each column was an
ordinary descriptor of that same checked anchor.

Reuse those facts only for **whole-model projections** whose fields are exact
built-in Attr/FKAttr/deferred-FK descriptors and whose effective relation identity
is still that anchor. Built-in deferred descriptors do not evaluate their target
callbacks when reading owner/relation identity; binding must already succeed
before this decision is reached. Custom metaclasses and descriptor subclasses,
CTE/scalar/aggregate expressions, and explicit projections keep general dispatch.
Aliases use their query relation, not their original codec owner.

This is a synchronous, construction-local eligibility check, **not a persistent
metadata cache**. Every factory call still checks the anchor's current backend
and metadata. Clause ownership checks, compilation checks, write builders and
result materialization are unchanged. An early broader projected-field candidate
added work on mixed-expression fallbacks; the final optimization deliberately
limits the extra scan to whole-model selections.

## Construction results

Six clean process phases, **B/C/B then C/B/C**, each with six trials of 50,000
builds and 5,000 warmup. GC is disabled during timing. Medians of 18 samples per
workload/revision; compiled SQL and parameters agree across all six invocations.

| Workload | Baseline builds/s | Candidate builds/s | Ratio |
| --- | ---: | ---: | ---: |
| Point read (whole model + predicate + limit) | 91,936 | 104,085 | 1.13× |
| Filtered whole-model chain | 42,405 | 44,627 | 1.05× |
| Explicit projection | 72,180 | 72,445 | 1.00× |
| Insert | 249,520 | 253,108 | 1.01× |
| Update | 127,741 | 129,722 | 1.02× |
| Aggregate projection | 110,766 | 112,801 | 1.02× |
| Mixed fields/aggregate + GROUP BY | 64,773 | 64,666 | 1.00× |
| Two-column model with deferred self-FK | 230,201 | 291,893 | 1.27× |

The deferred-FK workload measures repeated SELECT construction **after binding**,
not the initial callback's cost. Controls within approximately 2% are not claimed
as improvements. These are construction gains, not execution gains.

Separate profiling of 20,000 filtered builds:

| Function | Baseline calls / cumulative s | Candidate calls / cumulative s |
| --- | ---: | ---: |
| `require_model_columns` | 180,000 / 0.205 | 100,000 / 0.118 |
| `_require_sqlite_model` | 100,000 / 0.124 | 20,000 / 0.029 |
| `model_projection_uses_checked_anchor` | — | 20,000 / 0.039 |

Profile times are instrumented/nested and must not be added or treated as
throughput predictions. The residual metadata checks remain; this does not remove
all repeated checks mentioned in #481.

## Retained memory

Separate tracemalloc snapshots, 5,000 retained builds and three samples per
workload/revision. Median bytes/build include the retaining-list overhead.

| Retained output | Baseline bytes | Candidate bytes |
| --- | ---: | ---: |
| Finished point-read query | 529 | 526 |
| Finished filtered query | 773 | 773 |
| Explicit projection | 513 | 513 |
| Insert | 475 | 475 |
| Update | 528 | 527 |
| Aggregate | 506 | 506 |
| Mixed projection | 614 | 613 |
| Deferred-FK model select | 353 | 354 |
| Base + two paginated branches | 1,159 | 1,158 |
| All six intermediate filtered-chain stages | 2,325 | 2,326 |

Retained memory is approximately unchanged, including intermediate query chains.
No instance dictionary is materialized and no cache is retained by this change.
This is not a measurement of total/native RSS or transient allocation rate.

## End-to-end point reads

2,000 seeded rows, 500 operations/trial, 50 warmup, six rotating
raw/snekql/SQLAlchemy trials/invocation. Backend order alternates between phases.
Medians of 18 trials per adapter/revision:

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 12,239 | 13,320 |
| SQLite | snekql | 2,553 | 2,694 |
| SQLite | SQLAlchemy | 2,710 | 2,978 |
| MariaDB | raw | 12,011 | 12,565 |
| MariaDB | snekql | 2,528 | 2,499 |
| MariaDB | SQLAlchemy | 3,111 | 3,105 |

**No isolated runtime improvement is established.** SQLite controls rise more
than snekql, and MariaDB snekql moves slightly down. The construction CPU reduction
is clear; these composite transaction/driver measurements remain noisy.

Median snekql trial p99 latency: SQLite 0.697 → 0.652 ms; MariaDB 0.691 → 0.716 ms.
Median trial maximum heartbeat lateness: SQLite 0.171 → 0.163 ms; MariaDB
0.181 → 0.229 ms. Latency does not improve uniformly.

## Environment, evidence and validation

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6. Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, powersave governor;
no CPU pinning or host-wide load control. Private Btrfs disk-backed databases,
SQLite WAL/NORMAL, MariaDB redo flush policy 1 and binary logging off. All retained
measurements ran sequentially before our full suite; no tests were launched
alongside them. Memory and profiling were separate from primary timing.

[Construction metadata](results/select-metadata-481/construction-manifest.json),
[288 timing samples](results/select-metadata-481/construction-trials.csv), and
[60 memory samples](results/select-metadata-481/memory-trials.csv) retain source
revisions, interpreter, compiled output and parameters. The
[runtime manifest](results/select-metadata-481/manifest.json) and
[216 runtime trials](results/select-metadata-481/trials.csv) retain all twelve
point-read reports with environment/session policies. CSV `run` joins report
metadata; empty optional fields are null and lists remain JSON inside cells.
Every retained command exits zero with empty stderr. Raw reports, scripts,
profiles and validation logs remain in `/home/crpier/.cache/snekql-481-metadata/`.

Six new public-interface cases protect mixed-backend fields/scalars/models,
query-source identity for later joins and aliases, and successful/failed deferred
binding across repeated model/column selections. They pass on the baseline; an
unsafe anchor-only namespace check fails both backend cases. An initial malformed
Param declaration caused a collection error; it was corrected before the recorded
baseline/red/green cycle. Focused query/source/binding/extension tests: **763 passed**.
Full-suite and final CI/static status are recorded in the implementation PR.

## Reproduction

Use identical dependencies and a private disk-backed `TMPDIR` with
`PYTHON_CONTEXT_AWARE_WARNINGS=1` in each clean revision:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload point-read \
  --rows 2000 --operations 500 --trials 6 --warmup 50
# Repeat with --backend mariadb, interleaving baseline/candidate as above.
```

Save this script outside the worktrees; run with `timing`, then separately
`memory` and `profile OUTPUT.prof`. The source-path insertion prevents a shared
editable installation from silently selecting the wrong worktree.

```python
import cProfile
import dataclasses
import json
import os
import subprocess
import sys
from typing import ClassVar

sys.path.insert(0, os.getcwd())
from benchmarks.construction import (
    WORKLOADS,
    BenchUser,
    measure_memory,
    measure_throughput,
)
from snekql import sqlite
import snekql._query_state


class Node[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Node[sqlite.Row]]]
    id: sqlite.Col[int] = sqlite.Integer(primary_key=True)
    parent: sqlite.FKCol[Node, int | None] = sqlite.ForeignKey(
        lambda: Node.id, default=None
    )


def mixed():
    return sqlite.select(
        BenchUser.id,
        BenchUser.id,
        BenchUser.id,
        BenchUser.id,
        BenchUser.id,
        BenchUser.id,
        BenchUser.id.count(),
    ).group_by(BenchUser.id)


WORKLOADS = dict(
    WORKLOADS,
    aggregate=lambda: sqlite.select(BenchUser.id.count()),
    mixed=mixed,
    deferred=lambda: sqlite.select(Node),
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
