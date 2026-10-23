# Fixed COUNT/AVG decoders — #510

Measured 2026-10-23 (UTC): clean merged baseline `45fce31` versus implementation
`4a9a63e`. Incremental measurements, not multiplied previous gains.

## Change

Exact built-in COUNT/AVG nodes resolve to stateless, NULL-aware int/float functions
instead of passing every value through projection/selectable/aggregate dispatch.
COUNT(*) and COUNT(column), empty inputs, numeric normalization and independence
from source logical/projection/numeric policies retain their contracts. Ordinary
columns still take their existing fast path; unknown nodes retain general dispatch.
Other aggregates retain their semantics, with two additional setup comparisons.
No query/capability cache, SQL rewrite, API, dependency, driver or checkpoint change.

## Wide SQLite reads

Private disk-backed SQLite, 2,000 numeric rows `(id, units, amount) = (n, 2*n, n/2)`.
Queries return 1,000 rows/singleton groups. Non-COUNT named results have three
optional float fields; COUNT has optional int fields. These result types differ
from #508: compare revisions within this report, not across reports.

Prebuilt queries, shared transactions, six B/C alternating processes. Each case
uses six 100-operation trials after ten warmups per process: **18 samples per
workload/revision**. Every read checks row count and endpoint values.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control | 314.98 | 321.62 | 1.021× |
| Three extrema control | 301.56 | 306.63 | 1.017× |
| One AVG + two extrema | 294.50 | 336.18 | **1.142×** |
| Three AVGs | 339.05 | 487.12 | **1.437×** |
| COUNT(*) + two column COUNTs | 351.52 | 501.38 | **1.426×** |

Controls increase about 2%; targeted gains are larger. Singleton groups emphasize
materialization, not SQL aggregation over large input groups. No universal,
MariaDB or streaming throughput claim follows from these buffered SQLite results.

## Single-row results and investigation

Primary one-row trials use 2,000 operations after 200 warmups:

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 10,066 | 9,242 |
| Three extrema | 7,362 | 7,027 |
| One AVG + two extrema | 6,562 | 7,101 |
| Three AVGs | 8,008 | 9,381 |
| Three COUNTs | 8,412 | 7,492 |

These are mixed, including unfavorable controls and COUNT results. Longer ordinary
controls in both revision orders and CPU-2-pinned ordinary/extrema controls were
scheduled before observing primary results. Each series uses six processes, ten
5,000-operation trials after 1,000 warmups: **30 samples per combination/revision**.
Raw executes identical SQL/bindings and strict named-result validation, but not
snekql's full runtime contract. Adapter/workload order rotates per trial/process.

| Longer ordinary controls | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C alternating | snekql | 9,394 | 9,180 |
| Unpinned B/C alternating | raw | 28,329 | 27,156 |
| Unpinned C/B alternating | snekql | 10,104 | 9,534 |
| Unpinned C/B alternating | raw | 28,950 | 26,841 |
| CPU-2-pinned C/B alternating | snekql | 12,112 | 12,226 |
| CPU-2-pinned C/B alternating | raw | 33,927 | 34,074 |

Pinned extrema: snekql **9,719 → 9,765**, raw **33,613 → 33,775**. Pinned snekql
main-thread CPU: ordinary **75.407 → 74.730 µs/read**, extrema
**95.019 → 94.560 µs/read**. These controls are approximately stable under pinning;
the unpinned decreases remain published, not normalized away by raw ratios.

The unfavorable primary COUNT result prompted an additional matched COUNT/raw
repeat, using the same longer-trial protocol, C/B alternating, first unpinned then
CPU-2-pinned. Both use the COUNT result model and identical SQL/validation.

| COUNT repeat | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned | snekql | 7,225 | 8,123 |
| Unpinned | raw | 26,655 | 26,744 |
| Pinned | snekql | 9,815 | 10,144 |
| Pinned | raw | 33,163 | 33,855 |

Pinned COUNT main-thread CPU: **94.058 → 90.810 µs/read**. The primary COUNT decline
does not persist in these repeats, but they do not fully explain the original
movement. Pinning changes conditions and does not provide exclusive host control.
All series are retained separately. **No general point-read improvement or blanket
absence-of-regression claim is made.**

Independent standard-fixture comparative runs follow each primary timing process
after its database closes: per-operation query construction/per-read transactions,
six rotating adapter trials of 2,000 operations after 200 warmups. Medians:

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 12,612 | 12,500 |
| snekql | 2,915 | 2,907 |
| SQLAlchemy | 3,060 | 2,774 |

This is not the numeric fixture above and does not establish a point-read gain.

## Separate memory and profile evidence

Tracemalloc retains 20 reads × 1,000 rows, three samples/workload/revision:

| Workload | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary | 11,560,937 → 11,560,937 | 11,639,993 → 11,639,993 |
| Extrema | 11,560,966 → 11,560,966 | 11,641,318 → 11,641,318 |
| One AVG | 11,560,966 → 11,560,966 | 11,641,094 → 11,640,542 |
| Three AVGs | 11,545,350 → 11,545,350 | 11,621,454 → 11,620,230 |
| Three COUNTs | 10,107,593 → 10,107,593 | 10,183,809 → 10,182,585 |

Retention is unchanged and peaks approximately unchanged. This is not RSS or
isolated setup allocation. Stateless functions replace execution-local fallback
partials for these fixed domains; all resolution/setup remains inside timings.

Separate profiles over 100 × 1,000 rows show, for both three-AVG and three-COUNT:

- `_decode_projection_field`, `_decode_selectable`, `_decode_aggregate`: each
  **300,000 → 0 calls**.
- Candidate fixed converter: **300,000 calls**, retaining each numeric conversion.
- Final named-result materializations: **100,000 → 100,000**.

Profiles corroborate avoided dispatch, not throughput estimates. No required
column validation was removed: COUNT/AVG already used fixed numeric domains.

## Validation and provenance

Four new public parameterized cases pass on baseline/candidate, covering
SQLite/MariaDB × buffered/streamed execution. They exercise COUNT(*) versus nullable
column counts, empty/all-NULL inputs, negative fractional averages, exact numeric
types, changing validation flags, custom source policies and empty scalar subqueries.
Unsafe COUNT/AVG conversion, lost AVG NULL handling and accidental source decoding
mutations fail and are reverted. Focused coverage: **87 passed**. Full local suite:
**4,009 passed**, exit 0, 895.14s. Static/CI status is recorded in the PR. No private
call-count or speed assertions enter CI.

An initial test preflight used nonexistent `query.scalar()`; corrected to public
`backend.scalar(query)` before final baseline/candidate runs. This failed preflight
is retained in discovery logs, not counted as validation or performance evidence.
The benchmark correctness preflight passed all five workloads.

Published **1,218 samples**:

- [360 primary timings](results/fixed-aggregates-510/timing-trials.csv),
  [120 forward](results/fixed-aggregates-510/forward-trials.csv),
  [120 reverse](results/fixed-aggregates-510/reverse-trials.csv),
  [240 pinned controls](results/fixed-aggregates-510/pinned-trials.csv),
  [120 unpinned COUNT](results/fixed-aggregates-510/counts-unpinned-trials.csv),
  [120 pinned COUNT](results/fixed-aggregates-510/counts-pinned-trials.csv),
  [30 memory](results/fixed-aggregates-510/memory-trials.csv), and
  [probe commands/provenance](results/fixed-aggregates-510/probe-manifest.json).
- [108 comparative trials](results/fixed-aggregates-510/comparative-trials.csv) and
  [environment/session/command metadata](results/fixed-aggregates-510/comparative-manifest.json).

Full validation preceded timings. Owned timing, memory, profiles and follow-ups ran
sequentially; retained commands exited zero with clean source trees. Raw evidence:
`/home/crpier/.cache/snekql-510/`; discovery/mutations:
`/home/crpier/.cache/snekql-fixed-aggregate-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled runs pin to CPU 2. No exclusive host control;
visible-test checks cannot prevent other sessions starting work mid-measurement.

## Reproduction

Same dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, private disk-backed `TMPDIR`.
Save scripts outside source roots and run from exact revision worktrees above.
Primary: B/C alternating six processes; memory/profiles separate. After each primary
process, the independent comparative command is:

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
    key: float | None
    units: float | None
    amount: float | None


class Counts(BaseModel):
    key: int | None
    units: int | None
    amount: int | None


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


def query(width, shape):
    q = sqlite.select(Metric).where(Metric.id.lte(width))
    if shape == "plain":
        return q.project(
            Record, key=Metric.id, units=Metric.units, amount=Metric.amount
        ).order_by(Metric.id.asc())
    if shape == "counts":
        return (
            q.project(
                Counts,
                key=Metric.count_all(),
                units=Metric.units.count(),
                amount=Metric.amount.count(),
            )
            .group_by(Metric.id)
            .order_by(Metric.id.asc())
        )
    if shape == "extrema":
        fields = (Metric.id.min(), Metric.units.max(), Metric.amount.min())
    elif shape == "one":
        fields = (Metric.id.avg(), Metric.units.min(), Metric.amount.max())
    else:
        fields = (Metric.id.avg(), Metric.units.avg(), Metric.amount.avg())
    return (
        q.project(Record, key=fields[0], units=fields[1], amount=fields[2])
        .group_by(Metric.id)
        .order_by(Metric.id.asc())
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
                for shape in ("plain", "extrema", "one", "three", "counts"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        expected_first = (1, 1, 1) if shape == "counts" else (1, 2, 0.5)
                        expected_last = (
                            (1, 1, 1)
                            if shape == "counts"
                            else (width, 2 * width, width / 2)
                        )
                        assert (
                            rows[0].key,
                            rows[0].units,
                            rows[0].amount,
                        ) == expected_first
                        assert (
                            rows[-1].key,
                            rows[-1].units,
                            rows[-1].amount,
                        ) == expected_last
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

Keep beside `probe.py`. Phases 0–5, B/C alternating, then separately C/B alternating.

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

C/B alternating phases 0–5; imports the same `probe.py`.

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
            for shape in ("plain", "extrema"):
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

### COUNT repeats

Copy `pinned.py` to `counts.py`. Import `Counts as Record` instead of `Record`,
replace the workload tuple with `("counts",)`, and replace both expected endpoint
triples with `(1, 1, 1)`. Run C/B alternating phases 0–5 first with
`python counts.py PHASE_INDEX`, then a separate C/B series with
`taskset -c 2 python counts.py PHASE_INDEX`. These are separate series, not pooled.
