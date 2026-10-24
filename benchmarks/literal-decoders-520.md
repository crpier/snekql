# Execution-local native integer literal decoding — #520

Measured 2026-10-24 UTC. Clean baseline **`63f7790`** (merged #519) versus candidate
**`7936632`**. Incremental evidence; historical gains are not multiplied.

## Change and retained contracts

Exact built-in integer literals bind their existing policy decoder once per
execution, avoiding repeated structural discovery. **Every returned value still
passes the backend check and exact native-integer check.** The declared constant
is not substituted for the SQL result: UNION and recursive member rows can return
different values under the anchor's decode contract.

Owner-free literals remain non-NULL across missing joined rows. Derived references
retain their own source-absence context; empty scalars bypass a nonnullable source
codec. Intermediate application models remain bypassed; final validation remains
mandatory. Unknown/custom sources stay general. No persistent/global cache,
SQL rewrite, API/dependency/driver change or backend-specific core import.

Ordinary columns and built-in value expressions retain their earlier fast paths.
Other scalar/aggregate expressions incur an extra setup type comparison. Bound
policy methods/partials have execution-local cost; avoiding per-row discovery is
not proof of zero setup overhead.

## Wide buffered SQLite throughput

Private disk-backed SQLite, 2,000 `(id, units, amount) = (n, 2*n, n/2)` rows,
prebuilt queries/shared transaction, three optional named-result fields. Six
alternating B/C processes; six trials of 100 reads after ten warmups gives
**18 samples/workload/revision**. Each read consumes 1,000 rows and verifies count
and endpoint values.

- Ordinary: physical three-column projection, ordered by key.
- Physical extrema control: MIN(key), MAX(units), MIN(amount), singleton groups.
- One literal: `literal(1)` as key, ordinary units and amount.
- Three literals: `literal(1)`, `literal(2)`, `literal(3)` as the three outputs.

The result contract accepts integers for its float `amount` field, so the last
shape's final values are `(1, 2, 3.0)`; the source literal decoder still requires
native integers. Literal workloads are not equivalent to the varying physical
payloads—compare each shape only against itself across revisions.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection | 323.41 | 328.53 | 1.016× |
| Physical extrema | 296.57 | 313.00 | 1.055× |
| One literal | 297.00 | 366.03 | **1.232×** |
| Three literals | 292.61 | 477.35 | **1.631×** |

Physical control also improved, so do not attribute every change to this patch or
normalize against that moving control. These are buffered SQLite literal-heavy
reads, not evidence for all workloads, recursive traversal throughput, MariaDB or
streaming. Correctness coverage is not performance evidence.

## One-row evidence and unfavorable pinned controls

Primary one-row trials: six × 2,000 reads after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 9,666 | 11,476 |
| Physical extrema | 7,108 | 9,530 |
| One literal | 7,875 | 10,723 |
| Three literals | 8,507 | 8,617 |

Ordinary and physical controls moved substantially. Longer ordinary B/C and C/B
series and CPU-2-pinned ordinary/physical controls were scheduled before primary
results. Each uses six processes, ten 5,000-read trials after 1,000 warmups:
**30 samples/adapter/workload/revision**. Adapter/workload order rotates. Raw
consumes the same compiled SQL/bindings and validates the same strict result
model, but does not perform snekql's entire runtime contract.

| Ordinary follow-up | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 10,313 | 11,089 |
| Unpinned B/C | raw | 30,358 | 30,951 |
| Unpinned C/B | snekql | 11,615 | 11,642 |
| Unpinned C/B | raw | 30,877 | 30,405 |
| Pinned C/B | snekql | 12,231 | 12,117 |
| Pinned C/B | raw | 34,368 | 34,616 |

Initial pinned physical extrema: snekql **9,771 → 9,555**, raw
**33,987 → 34,296**. Main-thread CPU µs/read: ordinary **74.714 → 75.436**,
physical extrema **94.593 → 96.803**. Those ~0.9%/~2.2% snekql throughput declines
prompted a separate reversed-order pinned B/C series, using the identical protocol.

| Repeated pinned B/C | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Ordinary | snekql | 12,221 | 12,170 |
| Ordinary | raw | 34,245 | 33,660 |
| Physical extrema | snekql | 9,739 | 9,658 |
| Physical extrema | raw | 33,841 | 33,328 |

Repeated CPU µs/read: ordinary **74.771 → 75.061**, physical extrema
**94.874 → 95.616**. Smaller snekql declines persisted (~0.4%/~0.8%); raw declined
on this repeat as well. Do not claim the adverse result disappeared, normalize
by raw, or pool series. The extra setup condition is real, but its share of these
changes is not isolated. Ordinary-column dispatch is unchanged. CPU affinity is
not exclusive host control. No blanket non-regression or general point-read gain.

Independent comparative point reads use the standard fixture, build queries per
operation and open per-read transactions. After each primary process closes its
database: six rotating adapter trials × 2,000 operations after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,802 | 13,877 |
| snekql | 3,298 | 3,157 |
| SQLAlchemy | 3,140 | 3,246 |

## Output retention and execution allocation

Separate tracemalloc probes retain 20 reads × 1,000 rows, three trials per shape
and revision. These are traced output/peak allocations, not process RSS or
isolated constructor latency. No persistent declaration cache is added.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Ordinary | 10,894,441 → 10,894,441 | 10,970,313 → 10,970,313 |
| Physical extrema | 10,894,470 → 10,894,470 | 10,971,638 → 10,971,638 |
| One literal | 10,894,454 → 10,894,454 | 10,970,518 → 10,970,310 |
| Three literals | 10,587,625 → 10,587,625 | 10,663,945 → 10,663,753 |

Retention is unchanged; peaks flat/slightly lower. Three-literal payloads differ
from other shapes, so their smaller retention is not an optimization gain.
Bound methods/partials still have setup and execution-lifetime costs.

## Diagnostic profiles

Separate profiles: 100 × 1,000 rows, three literal projections.

| Call count | Baseline → Candidate |
| --- | ---: |
| Structural protocol checks | **300,900 → 900** |
| `_decode_projection_field` | **300,000 → 0** |
| `_decode_selectable` | **300,000 → 0** |
| Literal policy checks/decodes | 300,000 → 300,000 |
| Final named materializations | 100,000 → 100,000 |

Profiles corroborate removed discovery; they are not throughput estimates.

## Validation and provenance

Ten new public cases pass on baseline and candidate:

- SQLite buffered/streamed UNION reads reject promoted REAL values even with
  `validate=False`, despite a permissive final int-or-float contract. Subsequent
  valid reads return the actual member values, not the anchor's constant.
- SQLite/MariaDB buffered/streamed reads preserve signed-64 limits, owner-free
  constants across missing joins, derived absence, empty scalars, intermediate
  validator bypass and final validator execution.
- Both backends/modes recursively materialize changing integer member values,
  not a repeated seed. Partial final stream chunks and False/True/False validation
  reuse are covered.

Unsafe mutations: bypass native decoding → **2 failures**; substitute the declared
constant → **6 failures**; remove NULL wrappers → **4 errors**. Restored.
**122 focused tests pass**, including existing literal, recursive, UNION,
source-policy/dialect-extension and derived NULL-context regressions.

Full suite **4,058 passed**, exit 0, **1049.07s**. Ruff/format/ty and whitespace
checks pass; CI status is in the PR. Tests assert public results/errors, not
private call counts or speed. No failed/cancelled benchmark samples discarded.
All measured revisions clean; measurement commands exited zero. Owned tests,
timings, profiles and memory probes ran sequentially.

Published **1,140 samples**: 288 primary timing, 120 forward, 120 reverse,
240 initial pinned, 240 repeated pinned, 24 memory and 108 comparative trials.

- [Probe commands/metadata](results/literal-decoders-520/probe-manifest.json)
- [Primary timing](results/literal-decoders-520/timing-trials.csv)
- [Forward ordinary](results/literal-decoders-520/forward-trials.csv)
- [Reverse ordinary](results/literal-decoders-520/reverse-trials.csv)
- [Pinned C/B](results/literal-decoders-520/pinned-trials.csv)
- [Repeated pinned B/C](results/literal-decoders-520/pinned-reverse-trials.csv)
- [Memory](results/literal-decoders-520/memory-trials.csv)
- [Comparative trials](results/literal-decoders-520/comparative-trials.csv)
- [Comparative provenance](results/literal-decoders-520/comparative-manifest.json)

Raw evidence: `/home/crpier/.cache/snekql-520/`; discovery/tests/mutations:
`/home/crpier/.cache/snekql-literal-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F/28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled follow-ups pin CPU 2; no exclusive host control.

## Reproduction

Identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, private disk-backed
`TMPDIR`, exact clean revision worktrees; scripts outside worktrees. Save stdout
JSON per fresh process. Primary B/C alternation three times; memory/profiles
separately. After each primary timing process:

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
        (sqlite.literal(1), Metric.units, Metric.amount)
        if shape == "one"
        else (sqlite.literal(1), sqlite.literal(2), sqlite.literal(3))
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
                            (1, 2, 3.0) if shape == "three" else (1, 2, 0.5)
                        )
                        assert (rows[-1].key, rows[-1].units, rows[-1].amount) == (
                            (1, 2, 3.0)
                            if shape == "three"
                            else (1, 2 * width, width / 2)
                            if shape == "one"
                            else (width, 2 * width, width / 2)
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

Phases 0–5, C/B then separately B/C alternation; import the same `probe.py`.

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
