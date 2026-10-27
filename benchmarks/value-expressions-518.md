# Execution-local built-in value-expression decoding — #518

Measured 2026-10-24 UTC. Clean baseline **`cf86dd0`** (merged #517) versus candidate
**`b230b12`**. Incremental results, not multiplied historical gains.

## Change and contracts

Only exact built-in `ValueExpression` objects bind their native decoder once per
execution. Custom/unknown expressions and subclasses remain on the general path;
no dialect-specific leaf is imported into the core. Existing ordinary-column
resolution remains first. Scalars/aggregates incur one extra setup type check.

The native decoder is **still called for every value**: integer overflow promoted
to SQLite REAL remains a materialization error, even with `validate=False`.
Expression domains do not borrow source-column codecs or logical validators.
SQL NULL still follows expression nullability. LEFT-join handling retains the
original per-NULL `__nullable_when_extended__()` evaluation, not a speculative
precomputation: CASE/COALESCE can produce a value without an owner row. Non-NULL
values never trigger that evaluation. Existing CTE resolution carries each
source definition's NULL context and bypasses intermediate application models.

No persistent cache, SQL/API/driver/dependency changes, backend import, or global
capability memoization. A bound method (and a wrapper for nullable owners) costs
execution-local setup; removing per-row dispatch does not make setup free.

## Wide buffered SQLite measurements

Private disk-backed SQLite, 2,000 `(id, units, amount) = (n, 2*n, n/2)` rows.
Prebuilt queries, shared transaction, three optional fields in a named result.
Six alternating B/C processes; six trials of 100 reads after ten warmups gives
**18 samples/workload/revision**. Each read consumes 1,000 rows and verifies count
and endpoint values.

- Ordinary: physical three-column projection ordered by key.
- Physical extrema control: MIN(key), MAX(units), MIN(amount), singleton groups.
- One expression: `id.add(0)` plus two ordinary columns.
- Three expressions: `id.add(0)`, `units.add(0)`, `amount.add(0.0)`.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection | 316.87 | 322.59 | 1.018× |
| Physical extrema | 302.27 | 305.18 | 1.010× |
| One arithmetic expression | 175.42 | 355.45 | **2.026×** |
| Three arithmetic expressions | 104.45 | 498.06 | **4.768×** |

These are buffered SQLite arithmetic projection workloads, not estimates for all
expressions, LEFT joins, MariaDB, streaming, or all reads. CASE/text-function and
cross-backend correctness tests are not throughput evidence.

## Single-row controls and adverse results

Primary one-row trials: six × 2,000 reads after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 11,224 | 9,635 |
| Physical extrema | 7,852 | 7,097 |
| One arithmetic expression | 10,209 | 11,016 |
| Three arithmetic expressions | 9,132 | 12,208 |

The substantial ordinary/physical declines are retained. Longer ordinary B/C and
C/B runs and CPU-2-pinned ordinary/physical controls were scheduled before seeing
primary results. Each uses six processes and ten 5,000-read trials after 1,000
warmups: **30 samples/adapter/workload/revision**. Adapter/workload order rotates.
Raw executes the same compiled SQL/bindings, consumes the same result and builds
the same strict named model, but not snekql's entire runtime contract.

| Ordinary follow-up | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 10,185 | 11,202 |
| Unpinned B/C | raw | 31,221 | 29,851 |
| Unpinned C/B | snekql | 10,969 | 10,807 |
| Unpinned C/B | raw | 28,969 | 31,837 |
| Pinned C/B | snekql | 12,206 | 12,185 |
| Pinned C/B | raw | 34,001 | 34,411 |

Pinned physical extrema: snekql **9,746 → 9,705**, raw **33,820 → 34,054**.
Main-thread CPU µs/read: ordinary **74.830 → 75.000**, physical extrema
**94.714 → 95.253**. These small pinned decreases are retained. Added setup cost
is not causally isolated, and the larger primary declines remain incompletely
explained. No normalization against moving raw controls or blanket non-regression
claim; CPU affinity is not exclusive host control.

Independent comparative point reads use the standard fixture, construct queries
per operation, and open a transaction per read. After each primary process closes
its database: six rotating adapter trials × 2,000 operations after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 11,914 | 12,352 |
| snekql | 2,957 | 2,845 |
| SQLAlchemy | 2,744 | 2,916 |

Do not combine these protocols or infer general point-read improvement from the
targeted arithmetic gains.

## Output memory and execution allocation

Separate tracemalloc probes retain 20 reads × 1,000 rows, three trials per shape
and revision. No persistent declaration cache is introduced. These are traced
retained-output/peak allocations, not RSS or isolated constructor latency.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Ordinary | 10,894,441 → 10,894,441 | 10,970,305 → 10,970,305 |
| Physical extrema | 10,894,598 → 10,894,470 | 10,971,694 → 10,971,630 |
| One expression | 10,894,463 → 10,894,463 | 10,971,271 → 10,970,031 |
| Three expressions | 10,894,427 → 10,894,427 | 10,971,515 → 10,969,699 |

Target output retention is unchanged; physical-control retention differs by 128
bytes (<0.002%). Peaks are flat/slightly lower. This does not establish zero
setup cost for bound methods or nullable-owner closures.

## Profiles: avoided dispatch, required checks retained

Separate diagnostic profiles of 100 × 1,000 rows, three arithmetic expressions:

| Call count | Baseline → Candidate |
| --- | ---: |
| Structural protocol checks | **601,200 → 1,200** |
| `_decode_projection_field` | **300,000 → 0** |
| `_decode_selectable` | **300,000 → 0** |
| `ValueExpression.__decode__` | 300,000 → 300,000 |
| Final named-result materializations | 100,000 → 100,000 |

Profiles are not throughput evidence. All native-domain checks and final result
construction are retained; the change removes discovery, not required decoding.

## Validation and provenance

Fourteen new public transaction tests pass on baseline and candidate:

- SQLite overflow rejects native-domain drift in buffered/streamed reads under
  False/True/False validation, with a subsequent valid read in the transaction.
- SQLite/MariaDB × buffered/streamed × direct/CTE projections retain integer,
  float, string and nullable domains; arithmetic, LOWER, CHAR_LENGTH, COALESCE and
  CASE; final validators run, deliberately rejecting intermediate validators do
  not run.
- SQLite/MariaDB × buffered/streamed joins distinguish present/absent owners from
  CASE literal and COALESCE fallback values; partial final stream chunks retained.

Unsafe mutations: bypass native decoding → **2 failures**; remove NULL-extension
handling → **4 errors**; treat present values as absent → **4 failures**. Restored.
**92 focused tests pass**, including existing source policy/dialect extensions,
derived NULL contexts, arithmetic, functions, CASE and labels. Assertions use
public results/errors, not private call counts or speed thresholds.

Full suite **4,048 passed**, exit 0, **1026.76s**. Ruff/format/ty and whitespace
checks pass. CI status is in the PR. No failed/cancelled benchmark samples were
silently discarded. All measured revisions were clean; commands exited zero.
Owned tests/timings/profiles/memory ran sequentially.

Published **900 samples**: 288 primary timing, 120 forward, 120 reverse,
240 pinned, 24 memory and 108 comparative trials.

- [Probe commands/metadata](results/value-expressions-518/probe-manifest.json)
- [Primary timing](results/value-expressions-518/timing-trials.csv)
- [Forward ordinary](results/value-expressions-518/forward-trials.csv)
- [Reverse ordinary](results/value-expressions-518/reverse-trials.csv)
- [Pinned controls](results/value-expressions-518/pinned-trials.csv)
- [Memory](results/value-expressions-518/memory-trials.csv)
- [Comparative trials](results/value-expressions-518/comparative-trials.csv)
- [Comparative provenance](results/value-expressions-518/comparative-manifest.json)

Raw evidence: `/home/crpier/.cache/snekql-518/`; discovery and test/mutation logs:
`/home/crpier/.cache/snekql-value-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F/28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled follow-ups pin CPU 2; no exclusive host control.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, private disk-backed
`TMPDIR`, exact clean revision worktrees, and scripts outside those worktrees.
Save each fresh process's stdout JSON. Primary B/C alternation three times;
profile/memory separately. After each primary timing process, run:

```bash
python -m benchmarks.compare --backend sqlite --workload point-read \
    --rows 2000 --operations 2000 --trials 6 --warmup 200
```

### Primary: `python probe.py timing`, `memory` or `profile`

```python
import asyncio, cProfile, gc, json, os, platform, subprocess, sys, tempfile, time, tracemalloc
from pathlib import Path

sys.path.insert(0, os.getcwd())
import sqlite3
from typing import ClassVar
from pydantic import BaseModel
from snekql import sqlite


class Metric[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[Metric[sqlite.Row]]]
    id: Metric.Col[int] = sqlite.Integer(primary_key=True)
    units: Metric.Col[int] = sqlite.Integer()
    amount: Metric.Col[float] = sqlite.Real()


class Record(BaseModel):
    key: int | None
    units: int | None
    amount: float | None


async def seed(path, rows):
    async with await sqlite.Database.initialize(
        sqlite.Config(database=path, pool_size=1, durability="normal")
    ) as db:
        await db.migrate({"001": sqlite.scaffold([Metric])})
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executemany(
            "INSERT INTO metric (id,units,amount) VALUES (?,?,?)",
            [(n, 2 * n, n / 2) for n in range(1, rows + 1)],
        )


class Role:
    pass


def query(width, shape):
    q = sqlite.select(Metric).where(Metric.id.lte(width))
    if shape == "plain":
        return q.project(
            Record, key=Metric.id, units=Metric.units, amount=Metric.amount
        ).order_by(Metric.id.asc())
    if shape == "physical":
        return (
            q.project(
                Record,
                key=Metric.id.min(),
                units=Metric.units.max(),
                amount=Metric.amount.min(),
            )
            .group_by(Metric.id)
            .order_by(Metric.id.asc())
        )
    fields = (
        (Metric.id.add(0), Metric.units, Metric.amount)
        if shape == "one"
        else (Metric.id.add(0), Metric.units.add(0), Metric.amount.add(0.0))
    )
    return q.project(Record, key=fields[0], units=fields[1], amount=fields[2]).order_by(
        Metric.id.asc()
    )


async def main():
    mode = sys.argv[1]
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "read.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
        ):
            for width in (1, 1000) if mode == "timing" else (1000,):
                for shape in ("plain", "physical", "one", "three"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        assert (rows[0].key, rows[0].units, rows[0].amount) == (
                            1,
                            2,
                            0.5,
                        )
                        assert (rows[-1].key, rows[-1].units, rows[-1].amount) == (
                            width,
                            2 * width,
                            width / 2,
                        )
                        return rows

                    for _ in range(200 if width == 1 else 10):
                        await read()
                    if mode == "profile":
                        profile = cProfile.Profile()
                        profile.enable()
                        for _ in range(100):
                            await read()
                        profile.disable()
                        revision = subprocess.check_output(
                            ["git", "rev-parse", "--short", "HEAD"], text=True
                        ).strip()
                        profile.dump_stats(
                            str(Path(__file__).parent / f"{revision}-{shape}.prof")
                        )
                        continue
                    for trial in range(6 if mode == "timing" else 3):
                        result = dict(
                            shape=shape, rows_per_operation=width, trial=trial + 1
                        )
                        if mode == "timing":
                            operations = 2000 if width == 1 else 100
                            start = time.perf_counter()
                            for _ in range(operations):
                                await read()
                            elapsed = time.perf_counter() - start
                            result.update(
                                operations=operations,
                                seconds=elapsed,
                                ops_s=operations / elapsed,
                            )
                        else:
                            gc.collect()
                            tracemalloc.start()
                            before = tracemalloc.get_traced_memory()[0]
                            retained = [await read() for _ in range(20)]
                            gc.collect()
                            current, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            result.update(
                                retained_rows=20000,
                                retained_bytes=current - before,
                                peak_bytes=peak - before,
                            )
                            del retained
                        samples.append(result)
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
                platform=platform.platform(),
                mode=mode,
                samples=samples,
            )
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
```

### Ordinary controls: `python followup.py PHASE_INDEX`

Keep beside `probe.py`; phases 0–5, B/C then separately C/B alternation.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from probe import Record, seed, query, sqlite


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
            q = query(1, "plain")
            compiled = q.compile()

            async def snekql_read():
                rows = await tx.fetch_all(q)
                assert len(rows) == 1
                row = rows[0]
                assert (row.key, row.units, row.amount) == (1, 2, 0.5)

            async def raw_read():
                async with raw.execute(compiled.sql, compiled.params) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
                row = Record.model_validate(
                    dict(zip(("key", "units", "amount"), rows[0], strict=True)),
                    strict=True,
                    by_alias=False,
                    by_name=True,
                )
                assert (row.key, row.units, row.amount) == (1, 2, 0.5)

            for op in (snekql_read, raw_read):
                for _ in range(1000):
                    await op()
            for trial in range(10):
                order = (("snekql", snekql_read), ("raw", raw_read))
                if (trial + int(sys.argv[1])) % 2:
                    order = tuple(reversed(order))
                for adapter, op in order:
                    cpu_start = time.thread_time()
                    start = time.perf_counter()
                    for _ in range(5000):
                        await op()
                    elapsed = time.perf_counter() - start
                    cpu_elapsed = time.thread_time() - cpu_start
                    samples.append(
                        dict(
                            adapter=adapter,
                            trial=trial + 1,
                            operations=5000,
                            seconds=elapsed,
                            main_thread_cpu_seconds=cpu_elapsed,
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
                affinity=sorted(os.sched_getaffinity(0)),
                samples=samples,
            )
        )
    )


asyncio.run(main())
```

### Pinned controls: `taskset -c 2 python pinned.py PHASE_INDEX`

Phases 0–5, C/B alternation; import the same `probe.py`.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from probe import Record, seed, query, sqlite


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
            operations = []
            for shape in ("plain", "physical"):
                q = query(1, shape)
                compiled = q.compile()

                def build(q, compiled):
                    async def snekql_read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == 1
                        row = rows[0]
                        assert (row.key, row.units, row.amount) == (1, 2, 0.5)

                    async def raw_read():
                        async with raw.execute(compiled.sql, compiled.params) as cursor:
                            rows = await cursor.fetchall()
                        assert len(rows) == 1
                        row = Record.model_validate(
                            dict(zip(("key", "units", "amount"), rows[0], strict=True)),
                            strict=True,
                            by_alias=False,
                            by_name=True,
                        )
                        assert (row.key, row.units, row.amount) == (1, 2, 0.5)

                    return snekql_read, raw_read

                for adapter, op in zip(
                    ("snekql", "raw"), build(q, compiled), strict=True
                ):
                    operations.append((shape, adapter, op))
            for _, _, op in operations:
                for _ in range(1000):
                    await op()
            for trial in range(10):
                offset = (trial + int(sys.argv[1])) % len(operations)
                for shape, adapter, op in operations[offset:] + operations[:offset]:
                    cpu_start = time.thread_time()
                    start = time.perf_counter()
                    for _ in range(5000):
                        await op()
                    elapsed = time.perf_counter() - start
                    cpu_elapsed = time.thread_time() - cpu_start
                    samples.append(
                        dict(
                            shape=shape,
                            adapter=adapter,
                            trial=trial + 1,
                            operations=5000,
                            seconds=elapsed,
                            main_thread_cpu_seconds=cpu_elapsed,
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
                affinity=sorted(os.sched_getaffinity(0)),
                samples=samples,
            )
        )
    )


asyncio.run(main())
```
