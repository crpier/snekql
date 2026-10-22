# Ordinary-column protocol dispatch — #494

Measured 2026-10-22 against clean `84e6f0d` (all four construction PRs merged)
and clean implementation `bb3473b`. Follow-up measurements use `2eb955b`, which
only adds policy-only regression cases; production code is identical.
[Combined earlier gains](combined-construction-481.md) are measured separately.

## Change and contract

SQL rendering and execution-local projection setup repeatedly perform structural
protocol inspection even when a stock column lacks the required extension hook.
`_column_protocols.py` supplies a narrow negative check for exact `Attr`, `FKAttr`
and `_DeferredFKAttr` implementations. It preserves nominal/registered protocol
membership, checks the instance dictionary, and scans the actual class MRO's
attribute dictionaries without executing descriptors. Subclasses, installed
hooks and unknown expressions retain the original structural checks.

There is **no capability cache**, no backend import in the core, no bypass of
column decoding/validation, and no change to transaction or deadline policies.
In particular, policy decoding still precedes dialect decoding, which still
precedes ordinary column decoding. A policy-only instance hook is sufficient
without any SQL extension hook. Helpers do not change expression SQL/parameters.

## Compilation

B/C/B then C/B/C, six trials of 20,000 compilations after 2,000 warmups in each
fresh process. GC is disabled during timing. Queries are prebuilt, so this
measures public `.compile()`, not builder construction or execution. Each median
has 18 samples/revision, and SQL/parameters agree across all six processes.

| Query | Baseline compiles/s | Candidate compiles/s | Ratio |
| --- | ---: | ---: | ---: |
| Whole model | 40,013 | 48,737 | 1.22× |
| Named projection | 38,110 | 45,431 | 1.19× |
| Join | 18,038 | 21,705 | 1.20× |
| Arithmetic expression | 56,763 | 55,945 | 0.99× |
| Literal-only projection control | 118,820 | 126,901 | 1.07× |

The targeted cases improve consistently across phases. This is **not a general
expression-compilation speedup**: arithmetic is 1.4% lower in these samples.
Literal-control process medians span roughly 109–133k on baseline and 119–128k
on candidate; its pooled increase is not attributed to the optimization.

Separate tracemalloc snapshots retain 5,000 compiled outputs, three samples per
case/revision. Rounded median bytes are unchanged: model **228**, projection
**260**, join **410**, arithmetic **222**, literal **199**. Setup/imports, transient
allocations and native RSS are outside these snapshots.

## Point-read execution

The comparative driver uses 2,000 seeded rows, 2,000 operations/trial, 200 warmups,
six rotating adapter trials per invocation and alternating backend order by phase.
Each table entry is the median of 18 samples:

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 13,553 | 12,465 |
| SQLite | snekql | 2,709 | 2,792 |
| SQLite | SQLAlchemy | 2,998 | 2,929 |
| MariaDB | raw | 12,482 | 11,852 |
| MariaDB | snekql | 2,534 | 2,592 |
| MariaDB | SQLAlchemy | 3,131 | 3,032 |

Snekql medians rise 3.0%/2.3%, but raw/Core controls move too. **No general
end-to-end speedup is claimed.** Snekql median trial p99: SQLite 0.666 → 0.670 ms,
MariaDB 0.747 → 0.738 ms. Neither is an attributed latency improvement.

A second diagnostic crosses model/projection output, prebuilt/rebuilt query, and
shared/per-operation transaction. Six trials of 2,000 operations after 200 warmups
in each process, again 18 samples per case/revision. Every operation checks the
returned row. Shared transactions deliberately amortize lifecycle work; they are
not semantically equivalent to one transaction per read.

| Output / query / transaction | SQLite baseline → candidate ops/s | MariaDB baseline → candidate ops/s |
| --- | ---: | ---: |
| Projection / prebuilt / shared | 8,046 → 7,992 | 6,123 → 6,925 |
| Projection / prebuilt / per-read | 3,602 → 3,553 | 3,205 → 3,295 |
| Projection / rebuilt / shared | 5,229 → 5,158 | 4,422 → 4,666 |
| Projection / rebuilt / per-read | 2,747 → 2,589 | 2,500 → 2,618 |
| Model / prebuilt / shared | 8,694 → 7,337 | 7,096 → 7,354 |
| Model / prebuilt / per-read | 3,925 → 3,808 | 3,364 → 3,347 |
| Model / rebuilt / shared | 7,082 → 7,402 | 6,246 → 6,060 |
| Model / rebuilt / per-read | 3,474 → 3,684 | 3,091 → 3,183 |

These mixed results should not be cherry-picked into a runtime claim. In
particular, the 16% SQLite model/prebuilt/shared decrease prompted a longer check.

### SQLite follow-up

Same disk policy, query and shared-transaction case. Six fresh processes B/C/B
then C/B/C; ten trials of 5,000 reads after 1,000 warmups, alternating raw/snekql
order within each process. Raw uses the same row data and Pydantic validation as
a driver control, not a claim to reproduce the full immutable model contract.

| Adapter | Baseline ops/s (30 samples) | Candidate ops/s (30 samples) |
| --- | ---: | ---: |
| snekql | 8,397 | 8,563 |
| raw | 26,903 | 27,022 |

The large decrease **did not reproduce**. Baseline process medians were
8,700 / 8,224 / 8,337; candidate 8,563 / 8,422 / 8,586. The modest pooled increase
also does not establish a general runtime improvement. The original unfavorable
samples remain in the evidence, not replaced by this follow-up.

## Profiles and validation

Profiles are separate from timing. In 2,000 prebuilt shared-transaction SQLite
projection reads, structural protocol checks fall **24,001 → 4,001** and generic
static attribute lookups **24,000 → 4,000**. All 8,000 selectable render calls and
6,000 decoder resolutions remain; 20,000 guarded negative checks replace the
removed generic checks. This confirms the dispatch mechanism, not an eliminated
validation contract. Instrumented plan cumulative time is **0.313 → 0.354 s**;
profiling overhead and the guard's own work mean the profile alone does not prove
faster execution. The compilation claim comes from unprofiled measurements.

Public tests cover instance-installed operand/projection hooks on both backends,
buffered/streamed dialect and policy decoders, validation changes on query reuse,
and policy-only hooks. Incorrect Attr-first rendering/decoding and a deliberately
wrong policy-hook guard fail these tests. Subclass policies, aliases, deferred
binding, joins, RETURNING, rich codecs and telemetry also receive focused coverage.
Final local/CI results are recorded in the PR.

An early broad test attempt omitted `PYTHON_CONTEXT_AWARE_WARNINGS=1` and hit the
shared `/tmp` quota during MariaDB setup; it is not counted as passing validation.
Correctly configured focused suites passed. A first full suite passed 3,941 cases;
a final full suite is run again after adding two policy-only cases. All timing
precedes those test runs, except the explicitly separate SQLite follow-up, which
runs after the first full suite and before the final one.

## Evidence and environment

The [runtime manifest](results/column-protocols-494/manifest.json) and
[216 adapter trials](results/column-protocols-494/trials.csv) retain commands,
source, native policies and environment. Additional files:

- [180 compilation trials](results/column-protocols-494/compile-trials.csv),
  [30 memory samples](results/column-protocols-494/memory-trials.csv),
  [probe metadata](results/column-protocols-494/probe-manifest.json).
- [576 execution diagnostics](results/column-protocols-494/execution-trials.csv),
  [execution metadata](results/column-protocols-494/execution-manifest.json).
- [120 SQLite follow-up trials](results/column-protocols-494/followup-trials.csv),
  [follow-up metadata](results/column-protocols-494/followup-manifest.json).

All retained commands exit zero with empty stderr and clean worktrees. CSV `run`
joins metadata. CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0,
aiosqlite 0.22.1, aiomysql 0.3.2, anyio 4.15.1, SQLAlchemy 2.1.1, greenlet 3.5.6;
i7-14700F, 28 logical CPUs, powersave, no pinning or exclusive host control.
Private Btrfs disk-backed databases; SQLite WAL/NORMAL; MariaDB redo flush policy
1, binary logging off. The runner waits for visible Python tests before each
command; other sessions can still start work during a command.

Raw reports, profiles and logs remain in `/home/crpier/.cache/snekql-494/`.

## Reproduction

Use identical dependencies and a private disk-backed `TMPDIR`, with
`PYTHON_CONTEXT_AWARE_WARNINGS=1`. Run from the exact worktrees above. The comparative
command is `python -m benchmarks.compare --backend sqlite --workload point-read
--rows 2000 --operations 2000 --trials 6 --warmup 200`, and likewise for MariaDB.
Save the following probes outside the source trees; their source-path insertion
prevents a shared editable installation from silently choosing the other checkout.

### Compilation: `python compile.py timing`, `memory`, or `profile OUTPUT.prof`

```python
import cProfile
import dataclasses
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
from pydantic import BaseModel
from snekql import sqlite
from benchmarks._models_sqlite import BenchUser, BenchProfile
from benchmarks._comparison_contract import Record
from benchmarks.construction import measure_throughput, measure_memory


class One(BaseModel):
    value: int


queries = {
    "model": sqlite.select(BenchUser).where(BenchUser.id.eq(42)),
    "projection": sqlite.select(BenchUser)
    .project(Record, id=BenchUser.id, email=BenchUser.email, payload=BenchUser.payload)
    .where(BenchUser.id.eq(42)),
    "join": sqlite.select(BenchUser)
    .join(BenchProfile, on=BenchUser.id.eq_col(BenchProfile.user_id))
    .where(BenchUser.id.eq(42)),
    "arithmetic": sqlite.select(BenchUser.id.add(1)).where(BenchUser.id.eq(42)),
    "literal_control": sqlite.select(BenchUser).project(One, value=sqlite.literal(1)),
}
report = dict(
    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
    python=sys.version,
    mode=sys.argv[1],
    samples=[],
    compiled={
        name: dict(sql=q.compile().sql, params=q.compile().params)
        for name, q in queries.items()
    },
)
if sys.argv[1] == "timing":
    for name, q in queries.items():
        report["samples"].append(
            dataclasses.asdict(
                measure_throughput(
                    name, q.compile, ops_per_trial=20000, trials=6, warmup=2000
                )
            )
        )
elif sys.argv[1] == "memory":
    for name, q in queries.items():
        for trial in range(3):
            report["samples"].append(
                dict(
                    label=name,
                    trial=trial + 1,
                    bytes=measure_memory(q.compile, count=5000),
                )
            )
else:
    op = queries["projection"].compile
    for _ in range(2000):
        op()
    p = cProfile.Profile()
    p.enable()
    for _ in range(20000):
        op()
    p.disable()
    p.dump_stats(sys.argv[2])
print(json.dumps(report))
```

### Execution: `python execution.py sqlite timing PREFIX`

Use `mariadb` for the other backend; `profile` writes a profile per case, separately
from timings.

```python
import asyncio
import cProfile
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_contract import Record
from snekql import sqlite, mariadb
from snekql.testing.mariadb import temporary_mariadb_server

backend, mode, output = sys.argv[1:]


@asynccontextmanager
async def database():
    if backend == "sqlite":
        from benchmarks._comparison_sqlite import seed
        from benchmarks._models_sqlite import BenchUser

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.db"
            await seed(path, 2000)
            async with await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db:
                yield sqlite, BenchUser, db
    else:
        from benchmarks._comparison_mariadb import seed
        from benchmarks._models_mariadb import BenchUser

        async with temporary_mariadb_server(transports={"tcp"}) as server:
            config = server.config(pool_size=1)
            await seed(config, 2000)
            async with await mariadb.Database.initialize(config) as db:
                yield mariadb, BenchUser, db


async def main():
    rows = []
    async with database() as (api, model, db):
        for shape in ("projection", "model"):

            def build():
                query = api.select(model)
                if shape == "projection":
                    query = query.project(
                        Record, id=model.id, email=model.email, payload=model.payload
                    )
                return query.where(model.id.eq(42))

            prebuilt = build()
            for rebuild in (False, True):
                for reuse in (True, False):
                    label = f"{shape}-{'rebuild' if rebuild else 'prebuilt'}-{'shared_tx' if reuse else 'per_tx'}"

                    async def one(tx):
                        result = await tx.fetch_all(build() if rebuild else prebuilt)
                        assert len(result) == 1
                        row = result[0]
                        assert (row.id, row.email, row.payload) == (
                            42,
                            "user42@example.com",
                            "x" * 32,
                        )

                    async def run(count):
                        if reuse:
                            async with db.transaction() as tx:
                                for _ in range(count):
                                    await one(tx)
                        else:
                            for _ in range(count):
                                async with db.transaction() as tx:
                                    await one(tx)

                    await run(200)
                    if mode == "profile":
                        profile = cProfile.Profile()
                        profile.enable()
                        await run(2000)
                        profile.disable()
                        profile.dump_stats(f"{output}-{label}.prof")
                    else:
                        for trial in range(6):
                            start = time.perf_counter()
                            await run(2000)
                            elapsed = time.perf_counter() - start
                            rows.append(
                                dict(
                                    label=label,
                                    trial=trial + 1,
                                    operations=2000,
                                    seconds=elapsed,
                                    ops_s=2000 / elapsed,
                                )
                            )
    print(
        json.dumps(
            dict(
                backend=backend,
                mode=mode,
                commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                dirty=bool(
                    subprocess.check_output(["git", "status", "--porcelain"], text=True)
                ),
                samples=rows,
            )
        )
    )


asyncio.run(main())
```

### SQLite follow-up: `python followup.py PHASE_INDEX`

Phase indices 0–5 alternate initial adapter order.

```python
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from benchmarks._comparison_sqlite import seed
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "followup.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
            connect(path, isolation_level=None) as raw,
        ):
            for sql in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA foreign_keys=ON",
                "PRAGMA busy_timeout=5000",
                "BEGIN",
            ):
                async with raw.execute(sql):
                    pass
            query = sqlite.select(BenchUser).where(BenchUser.id.eq(42))

            async def snekql_read():
                rows = await tx.fetch_all(query)
                assert len(rows) == 1
                row = rows[0]
                assert (row.id, row.email, row.payload) == (
                    42,
                    "user42@example.com",
                    "x" * 32,
                )

            async def raw_read():
                async with raw.execute(
                    "SELECT id, email, payload FROM bench_user WHERE id = ?", (42,)
                ) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
                row = Record.model_validate(
                    dict(zip(("id", "email", "payload"), rows[0], strict=True)),
                    strict=True,
                )
                assert (row.id, row.email, row.payload) == (
                    42,
                    "user42@example.com",
                    "x" * 32,
                )

            for op in (snekql_read, raw_read):
                for _ in range(1000):
                    await op()
            for trial in range(10):
                order = (("snekql", snekql_read), ("raw", raw_read))
                if (trial + int(sys.argv[1])) % 2:
                    order = tuple(reversed(order))
                for adapter, op in order:
                    start = time.perf_counter()
                    for _ in range(5000):
                        await op()
                    elapsed = time.perf_counter() - start
                    samples.append(
                        dict(
                            adapter=adapter,
                            trial=trial + 1,
                            operations=5000,
                            seconds=elapsed,
                            ops_s=5000 / elapsed,
                        )
                    )
            await raw.commit()
    print(
        json.dumps(
            dict(
                commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                dirty=bool(
                    subprocess.check_output(["git", "status", "--porcelain"], text=True)
                ),
                python=sys.version,
                samples=samples,
            )
        )
    )


asyncio.run(main())
```
