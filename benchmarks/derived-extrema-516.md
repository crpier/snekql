# Execution-local derived MIN/MAX decoding — #516

Measured 2026-10-24 UTC. Clean baseline **`0ce35b1`** (merged #515), candidate
**`cd390b1`** (implementation `7fe0235`, test-helper style cleanup `cd390b1`).
Incremental results; historical gains are not multiplied.

## Change and preserved behavior

Exact built-in MIN/MAX over exact built-in CTE outputs now resolve their source
projection decoder once per execution. Unlike extrema directly over a physical
column, derived extrema **adopt the definition's projection hooks**, including
dialect hooks. Resolution goes through the derived reference, preserving its
backend check's deferred fallback and definition-local NULL-extension context.
The outer nullable aggregate wrapper still skips decoding SQL NULLs.

No global/class capability cache, SQL rewrite, early ordering/numeric gate,
intermediate result validation, driver, dependency or public API change. Unknown
and custom sources remain general. Physical extrema retain their own distinct
policy. Source/final validation, codecs and required result construction remain.
Execution-local bound functions/closures replace repeated dispatch, not required
conversion. No persistent declaration cache is added. The ordinary-column fast
path still precedes expression resolution; other aggregates incur a small extra
setup condition, which is not free merely because row throughput improves.

## Wide buffered SQLite results

Private disk-backed database with 2,000 rows `(id, units, amount) = (n, 2*n, n/2)`.
Prebuilt queries, shared transaction, three optional fields in a named result.
Six alternating B/C processes, six trials of 100 reads after ten warmups:
**18 samples/workload/revision**. Every read checks row count and endpoint values.
Each read returns 1,000 rows/singleton groups.

- Ordinary: direct three-field projection, ordered by key.
- Physical control: MIN(key), MAX(units), MIN(amount), grouped by physical key.
- One derived extremum: MIN(key), units, amount over a CTE, grouped by all outputs.
- Three derived extrema: MIN(key), MAX(units), MIN(amount) over a CTE, grouped by key.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection | 326.72 | 329.42 | 1.008× |
| Physical extrema | 314.51 | 312.93 | 0.995× |
| One derived extremum | 110.96 | 312.28 | **2.814×** |
| Three derived extrema | 50.88 | 311.27 | **6.118×** |

These target buffered SQLite singleton groups, not all workloads. SQL-heavy or
large-group reads differ; MariaDB and streaming behavior tests are not throughput
evidence. This does not establish general point-read improvement.

## Single-row results, adverse outcomes and follow-ups

Primary one-row reads: six 2,000-operation trials after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 11,721 | 10,121 |
| Physical extrema | 9,171 | 9,420 |
| One derived extremum | 7,349 | 6,709 |
| Three derived extrema | 7,045 | 7,164 |

The ordinary and one-derived-extremum declines are retained. Longer ordinary
B/C and C/B series and CPU-2-pinned ordinary/physical controls were scheduled
before the primary results. After observing the target decline, additional
matched one-derived-extremum C/B series were run, unpinned and pinned separately.

Every longer series uses six processes, ten 5,000-read trials after 1,000 warmups:
**30 samples/adapter/workload/revision**. Adapter/workload order rotates. Raw
consumes the same compiled SQL/bindings and validates the same strict named
result, but does not perform snekql's complete runtime contract.

| Ordinary follow-up | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 10,454 | 11,256 |
| Unpinned B/C | raw | 29,984 | 30,928 |
| Unpinned C/B | snekql | 10,884 | 10,564 |
| Unpinned C/B | raw | 30,429 | 31,259 |
| Pinned C/B | snekql | 12,179 | 12,167 |
| Pinned C/B | raw | 34,547 | 34,539 |

Pinned physical extrema: snekql **9,743 → 9,664**, raw **34,192 → 34,257**.
Main-thread CPU µs/read: ordinary **75.046 → 75.116**, physical extrema
**94.862 → 95.588**. The small pinned physical decrease is retained; added setup
cost is not causally isolated. Do not normalize by moving raw controls or claim
blanket non-regression. Affinity is not exclusive host control.

| One-derived-extremum repeat | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned C/B | snekql | 6,519 | 6,770 |
| Unpinned C/B | raw | 28,819 | 30,078 |
| Pinned C/B | snekql | 7,460 | 7,855 |
| Pinned C/B | raw | 33,658 | 33,382 |

Pinned target CPU **125.087 → 118.480 µs/read**. The initial targeted decline did
not persist, but these repeats do not fully explain it. Publish all series,
without pooling protocols or silently selecting the favorable one.

Independent standard-fixture point reads follow each primary process after its
database closes. They build queries per operation and use per-read transactions:
six rotating adapter trials of 2,000 operations after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,839 | 13,810 |
| snekql | 3,215 | 3,097 |
| SQLAlchemy | 3,215 | 3,179 |

## Retained output and execution allocation

Separate tracemalloc probes retain 20 reads × 1,000 rows, three trials per shape
and revision. No persistent declaration cache is added; these measurements cover
retained outputs/peak execution allocations, not isolated constructor latency or
process RSS.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Ordinary | 10,894,441 → 10,894,441 | 10,970,305 → 10,970,305 |
| Physical extrema | 10,894,470 → 10,894,470 | 10,971,630 → 10,971,630 |
| One derived extremum | 10,894,619 → 10,894,619 | 10,971,611 → 10,971,083 |
| Three derived extrema | 10,894,654 → 10,894,654 | 10,971,598 → 10,971,918 |

Output retention is unchanged; peaks are approximately unchanged. Additional
execution-local bound functions/closures have a setup cost; peak equality is not
proof of zero setup overhead.

## Profiles corroborate avoided dispatch

Separate profiles consume 100 × 1,000 rows of the three-derived-extrema query.

| Count | Baseline → Candidate |
| --- | ---: |
| Structural protocol checks | **901,700 → 1,700** |
| `_decode_projection_field` | **600,000 → 0** |
| `_CteOutput.__decode_with_policy__` | **300,000 → 0** |
| Required column decodes | 300,000 → 300,000 |
| Final named-result materializations | 100,000 → 100,000 |

Profiles are diagnostic, not throughput estimates. The discovery profile used
three MIN fields; the published paired measurements use MIN/MAX/MIN and include
physical controls. No source policy or conversion is skipped to obtain the gain.

## Validation and evidence provenance

Fourteen new public transaction cases pass on baseline and candidate:
SQLite policy/dialect/combined hooks × buffered/streamed, and SQLite/MariaDB ×
buffered/streamed × column/aggregate domains. Cover nested CTEs/aliases, final
validator execution, intermediate-validator bypass, reuse across False/True/False
validation, negative/fractional values, native result types, empty/all-NULL
inputs, AVG/COUNT/SUM provenance, and rejected source validation.

Unsafe hook bypass produced 10 failures / 2 errors; forced validation-off produced
8 failures; removing nullable handling produced 10 errors. All mutations restored.
Existing derived NULL-context, scalar, joined-source, physical-extrema and fixed
aggregate regressions are included in **80 focused passing cases**.

Full final suite: **4,034 passed**, exit 0, **993.11s**. Ruff/format/ty and whitespace
checks pass; CI status is recorded in the PR. Tests assert public behavior, not
private call counts or timing. An early partial full run was cancelled/excluded
while fixing test-helper style diagnostics (numeric parameter annotation,
keyword-only boolean and explicitly passed query). Owned abandoned test servers
were stopped before restarting; no partial-run timing entered the data.

Published **1,140 samples**: 288 primary timings, 120 forward, 120 reverse,
240 pinned controls, 120 unpinned target, 120 pinned target, 24 memory,
108 independent comparative trials.

- [Probe commands/metadata](results/derived-extrema-516/probe-manifest.json)
- [Primary timing](results/derived-extrema-516/timing-trials.csv)
- [Forward ordinary](results/derived-extrema-516/forward-trials.csv)
- [Reverse ordinary](results/derived-extrema-516/reverse-trials.csv)
- [Pinned controls](results/derived-extrema-516/pinned-trials.csv)
- [Unpinned target](results/derived-extrema-516/target-unpinned-trials.csv)
- [Pinned target](results/derived-extrema-516/target-pinned-trials.csv)
- [Retained memory](results/derived-extrema-516/memory-trials.csv)
- [Comparative trials](results/derived-extrema-516/comparative-trials.csv)
- [Comparative provenance](results/derived-extrema-516/comparative-manifest.json)

All measured revisions were clean and every measurement command exited zero.
Owned tests/timings/memory/profiles ran sequentially. Raw evidence is retained in
`/home/crpier/.cache/snekql-516/`; discovery/tests/mutations are in
`/home/crpier/.cache/snekql-derived-extrema-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled follow-ups pin CPU 2. Host not exclusively held.

## Reproduction

Use the same dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, a private disk-backed
`TMPDIR`, and exact clean revision worktrees. Keep these scripts outside them.
Save stdout JSON per fresh process. Run primary B/C alternation three times;
profile and memory modes separately. After each primary timing process, run:

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
    tokens = (
        Metric.id.label("key"),
        Metric.units.label("units"),
        Metric.amount.label("amount"),
    )
    source = q.project(Record, key=tokens[0], units=tokens[1], amount=tokens[2]).cte(
        Role, name="metrics"
    )
    key, units, amount = (source.column(t) for t in tokens)
    if shape == "one":
        fields = (key.min(), units, amount)
        group = (key, units, amount)
    else:
        fields = (key.min(), units.max(), amount.min())
        group = (key,)
    return (
        sqlite.select(source)
        .project(Record, key=fields[0], units=fields[1], amount=fields[2])
        .group_by(*group)
        .order_by(key.asc())
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

Keep beside `probe.py`. Phases 0–5, B/C then separately C/B alternation.

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

### Target: `python target.py PHASE_INDEX`

Phases 0–5, C/B alternation; repeat separately with `taskset -c 2`.

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
            for shape in ("one",):
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
