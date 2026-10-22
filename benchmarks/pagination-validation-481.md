# Strict pagination argument validation — #481

Measured 2026-10-22 against clean baseline `a10cd17` and candidate `07a2c81`.
Both include #485/#486. **Neither includes #489, #490 or #492**; these results
must not be multiplied by those independent PRs' gains.

## Change and limits

The four model/compound `limit` and `offset` methods opt into a narrow validation
specialization. At decoration time, it requires exactly two required positional-
or-keyword parameters: an unannotated `self` and the exact `NonNegativeInt` alias.
The alias must still mean `Annotated[int, Ge(0)]`. Signature inspection permits
unresolved references, as Pydantic does. Changed constraints, defaults, parameter
kinds or annotations fall back to the general validator.

Only a call with two positional arguments, no keywords, and an **exact built-in
nonnegative int** invokes the original method directly. Everything else keeps
Pydantic: bools, negatives, floats, strings, integer subtypes, keywords, missing or
extra arguments and duplicate bindings. Domain-error translation remains intact.
Method bodies, immutable state transitions, ownership/backend checks and execution
validation are unchanged. Other `validate_boundary` callers do not opt in.

**Installed Pydantic plugins disable specialization**, even if disabled by their
configuration. Their hooks can impose policy on otherwise valid integers. A real
entry-point plugin in an isolated subprocess exposed the missing guard in an
early candidate; that candidate was fixed before publication. Discovery uses
standard distribution metadata, cached at setup, not Pydantic private internals.
The benchmark environment has no such plugins.

## Construction

Six fresh process phases, **B/C/B then C/B/C**, six trials of 50,000 builds per
case after 5,000 warmup calls. GC is disabled during timing. Each median has 18
samples per revision/case. Compiled SQL and parameters, captured outside timing,
agree across all six processes. These are SQLite builders using shared query
machinery; they are not measurements of SQL execution.

| Workload | Baseline builds/s | Candidate builds/s | Ratio |
| --- | ---: | ---: | ---: |
| Full point-read builder | 92,284 | 97,286 | 1.05× |
| Full filtered chain | 42,792 | 44,409 | 1.04× |
| Full projection chain | 74,278 | 76,652 | 1.03× |
| Insert (control) | 253,145 | 253,494 | 1.00× |
| Update (control) | 131,211 | 131,098 | 1.00× |
| Point-read builder, keyword limit (fallback) | 89,687 | 90,443 | 1.01× |
| Point-read builder, IntEnum limit (fallback) | 92,580 | 92,165 | 1.00× |
| Page an existing model builder | 217,017 | 253,385 | 1.17× |
| Page an existing compound builder | 219,293 | 254,808 | 1.16× |

The last two cases time only `.limit(10).offset(5)` on an existing immutable base.
They **exclude** base/compound construction; their larger gains do not describe
complete query construction. Keyword and subtype cases remain approximately
unchanged, as do the insert/update controls.

A separate profile of 20,000 filtered builds finds 40,000 pagination calls in
both revisions. The original boundary wrapper's cumulative time is 0.301 s;
the specialized wrapper's is 0.258 s, including unchanged method bodies. The
40,000 Pydantic call-wrapper/schema-validator dispatches disappear from this
construction profile, replaced by the exact-int/range check. All **180,000
`require_model_columns` calls remain** (0.206 → 0.204 s cumulative).
Profile times are instrumented and nested, not additive or throughput estimates.

## Memory and execution controls

Separate tracemalloc snapshot differences: 5,000 retained builds, three samples
per case/revision. Median bytes per retained build, including list overhead:

| Output | Baseline bytes | Candidate bytes |
| --- | ---: | ---: |
| Point read | 525 | 525 |
| Filtered | 775 | 772 |
| Projection | 509 | 513 |
| Insert | 475 | 475 |
| Update | 526 | 526 |
| Keyword point read | 526 | 526 |
| IntEnum point read | 525 | 526 |
| Page from existing model base | 291 | 291 |
| Page from existing compound base | 283 | 283 |
| Base + two independent branches | 1,157 | 1,158 |
| All six intermediate filtered-chain stages | 2,325 | 2,324 |

Retained query memory is approximately unchanged. There is no new per-query cache.
Decorator closures, signature checks and cached plugin-discovery setup are outside
these snapshots, so this does not establish zero additional process memory or
startup cost. Native RSS and transient allocation rate are not measured here.

Point-read execution used 2,000 seeded rows, 500 operations/trial, 50 warmup and
six rotating raw/snekql/SQLAlchemy trials per invocation. Backend order alternated
by phase. Each median contains 18 samples per adapter/revision:

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 10,896 | 12,368 |
| SQLite | snekql | 2,739 | 2,619 |
| SQLite | SQLAlchemy | 3,238 | 3,004 |
| MariaDB | raw | 13,090 | 12,957 |
| MariaDB | snekql | 2,655 | 2,649 |
| MariaDB | SQLAlchemy | 3,252 | 3,279 |

**No execution speedup is claimed.** SQLite snekql is 4.4% lower in this run,
while SQLAlchemy is 7.2% lower and raw is 13.5% higher; those mixed control movements
do not isolate an implementation effect. MariaDB snekql is approximately unchanged.
These short disk-backed trials cannot establish an end-to-end benefit from saving
a fraction of a microsecond in a builder.

Median snekql trial p99 latency: SQLite 0.649 → 0.654 ms; MariaDB 0.506 → 0.519 ms.
Median trial maximum heartbeat lateness: SQLite 0.147 → 0.162 ms; MariaDB
0.151 → 0.148 ms. These are observations, not attributed improvements.

## Evidence and validation

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6. Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, powersave governor;
no pinning or host-wide load isolation. Private Btrfs disk-backed databases,
SQLite WAL/NORMAL, MariaDB redo flush policy 1 and binary logging off.

Retained measurements ran sequentially, with profiles/memory separate and the
full suite starting only afterward. Before each command, the runner waited for
visible Python snektest/pytest runners. It cannot prevent other sessions from
starting work mid-command and does not imply exclusive host ownership.

[Construction metadata](results/pagination-validation-481/construction-manifest.json),
[324 timing samples](results/pagination-validation-481/construction-trials.csv), and
[66 memory samples](results/pagination-validation-481/memory-trials.csv) retain
revisions, source paths, plugin discovery, interpreter, compiled output and settings.
The [runtime manifest](results/pagination-validation-481/manifest.json) and
[216 runtime trials](results/pagination-validation-481/trials.csv) retain all twelve
point-read reports, session policies and environment. CSV `run` joins metadata;
empty optional values are null and lists remain JSON inside cells.
All retained measurement commands exit zero with empty stderr.

Eleven public-interface test cases pass on baseline and candidate. They cover
both backends and model/compound builders, strict invalid calls, redacted errors
and Pydantic causes, zero/large integers, subtype normalization, keyword arguments,
independent branches, SQLite row slices and a real installed validation plugin.
Deliberately accepting bools, changing forwarded values, omitting slices and
bypassing plugin policy produce failures. All unsafe variants were reverted.
An additional diagnostic compares **104 identical public call outcomes**, including
compiled SQL/parameters/types and error messages/causes.

Final focused query/union execution suite: **671 passed**. An initial collection
command had malformed Param declarations and was corrected. An intermediate
focused run overlapped an old full-suite process that had not stopped on SIGINT;
nine MariaDB cases hit the shared fixture's data-directory lock. That old owned
runner/server were stopped, and the final focused run passed. Two earlier
measurement series and the cancelled full suite are excluded, not counted as
final validation. Full-suite and final CI/static status are in the implementation PR.

Raw reports, parity diagnostics, scripts, profiles and logs remain in
`/home/crpier/.cache/snekql-481-validation/`; excluded experiments are under
`pre-plugin/` and `pre-opt-in/`.

## Reproduction

Use identical dependencies, no installed Pydantic plugins, a private disk-backed
`TMPDIR`, and `PYTHON_CONTEXT_AWARE_WARNINGS=1`:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload point-read \
  --rows 2000 --operations 500 --trials 6 --warmup 50
# Repeat for MariaDB and interleave revisions as above.
```

Save this script outside the source trees. Run from each worktree with `timing`,
then separately `memory` and `profile OUTPUT.prof`. Source-path insertion prevents
a shared editable install from selecting the other checkout.

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
