# Binding derived SUM provenance decoding — #512

Measured 2026-10-23 (UTC), clean merged baseline `9439822` versus implementation
`03a083a`. Incremental comparison, not multiplied earlier gains.

## Narrow change

For exact built-in SUM over an exact built-in CTE output, bind the existing
provenance `decode_sum` method once per execution. This removes repeated generic
expression/policy dispatch and output-slot lookup, not numeric validation.

**The numeric gate stays per value.** Moving it earlier could alter error timing or
source behavior. This change intentionally retains `require_numeric_source()` and
its source `.sum()` call. Derived numeric domains (including SUM over AVG/COUNT),
source-codec independence, empty-input NULLs and intermediate-model bypass remain.
Unknown/custom sources use existing paths. No global/query capability cache, SQL
rewrite, API, driver, dependency or checkpoint changes.

## Wide buffered SQLite results

Disk-backed database, 2,000 numeric rows `(id, units, amount) = (n, 2*n, n/2)`.
Prebuilt queries/shared transactions, three optional named-result fields. Six fresh
B/C alternating processes, six trials of 100 reads after ten warmups per case:
**18 samples/workload/revision**. Every read checks count and endpoint values.

Each read returns 1,000 rows/singleton groups. One-derived-SUM groups by all three
CTE outputs and sums the key while projecting the other two; three-derived-SUM
sums all three outputs grouped by key. Controls are ordinary projection and three
physical-column SUMs. Large input groups/SQL-heavy workloads can differ.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control | 325.09 | 333.10 | 1.025× |
| Physical SUM control | 439.20 | 450.10 | 1.025× |
| One derived SUM | 210.98 | 245.01 | **1.161×** |
| Three derived SUMs | 143.39 | 191.82 | **1.338×** |

Targeted gains exceed the approximately 2.5% control movement. No universal,
MariaDB or streaming throughput claim follows from these buffered SQLite results.

## Single-row evidence, including unfavorable results

Primary one-row cases use six 2,000-operation trials after 200 warmups:

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 9,040 | 10,680 |
| Physical SUM control | 7,561 | 8,549 |
| One derived SUM | 6,717 | 5,902 |
| Three derived SUMs | 6,589 | 6,778 |

Longer ordinary controls in both revision orders and pinned ordinary/physical-SUM
controls were scheduled before observing primary results. Each series: six fresh
processes, ten trials of 5,000 reads after 1,000 warmups, **30 samples per
combination/revision**. Adapter/workload order rotates by trial/process. Raw uses
the same compiled SQL/bindings and strict named-result validation, not snekql's
complete runtime contract.

| Ordinary controls | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C alternating | snekql | 11,206 | 10,822 |
| Unpinned B/C alternating | raw | 29,864 | 29,046 |
| Unpinned C/B alternating | snekql | 10,355 | 10,866 |
| Unpinned C/B alternating | raw | 29,486 | 28,848 |
| CPU-2-pinned C/B alternating | snekql | 12,163 | 12,006 |
| CPU-2-pinned C/B alternating | raw | 34,657 | 34,468 |

Pinned physical SUM: snekql **9,531 → 9,409**, raw **34,384 → 34,218**. Pinned
snekql main-thread CPU: ordinary **75.061 → 76.154 µs/read**, physical SUM
**97.075 → 98.453 µs/read**. Both snekql controls are about 1.3% slower in this
repeat; do not describe them as evidence of universal non-regression. The new
aggregate guard adds setup, but these runs do not isolate its causal cost.

The initial one-derived-SUM decrease prompted matched raw repeats, same longer
protocol, C/B alternating, unpinned then pinned to CPU 2:

| One-derived-SUM repeat | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned | snekql | 5,800 | 6,633 |
| Unpinned | raw | 28,809 | 28,615 |
| Pinned | snekql | 7,589 | 7,714 |
| Pinned | raw | 33,787 | 33,880 |

Pinned target CPU **122.776 → 120.756 µs/read**. The initial target decline does not
persist, but these repeats do not fully explain earlier movement. Pinning changes
conditions, not exclusive host control. All series remain separately published;
**no general point-read gain or blanket absence-of-regression claim**.

Independent standard-fixture comparative runs follow each primary timing process,
after its database closes: per-operation query construction/per-read transactions,
six rotating adapter trials of 2,000 operations after 200 warmups. Medians:

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 12,705 | 13,047 |
| snekql | 3,027 | 2,891 |
| SQLAlchemy | 2,979 | 3,081 |

The comparative snekql decrease is retained too. Results are not normalized by
control movement and do not establish a general execution improvement.

## Separate memory and profiles

Tracemalloc retains 20 reads × 1,000 rows, three samples/workload/revision:

| Workload | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary | 10,894,441 → 10,894,441 | 10,970,305 → 10,970,305 |
| Physical SUM | 10,894,470 → 10,894,470 | 10,971,246 → 10,971,246 |
| One derived SUM | 10,894,619 → 10,894,619 | 10,971,211 → 10,971,155 |
| Three derived SUMs | 10,894,654 → 10,894,654 | 10,971,198 → 10,971,462 |

Retention is unchanged; peaks approximately unchanged. This is not RSS or isolated
setup allocation. Bound provenance methods/NULL closures are execution-local,
not persistent query or output-row state.

Separate three-derived-SUM profiles consume 100 × 1,000 rows:

| Count | Baseline → Candidate |
| --- | ---: |
| Structural protocol checks | 301,700 → 1,700 |
| `_decode_projection_field` | 300,000 → 0 |
| `_CteOutput.__decode_sum__` | 300,000 → 0 |
| Provenance `decode_sum` | 300,000 → 300,000 |
| `require_numeric_source` | 300,000 → 300,000 |
| Source column `.sum()` gate | 300,000 → 300,000 |
| `_normalize_sum` | 300,000 → 300,000 |
| Final named-result materializations | 100,000 → 100,000 |

These counts corroborate avoided dispatch and retained numeric checks/conversions;
profile durations are not throughput estimates.

## Validation and provenance

Eight public cases pass on baseline/candidate: SQLite/MariaDB × buffered/streamed
× column/aggregate provenance. They exercise nested/aliased CTEs, SUM over AVG and
COUNT, negative/fractional/NULL values, exact native result types, empty/all-NULL
inputs, source numeric/projection policy independence, intermediate-validator
bypass, final validation and query reuse with changing validation flags.
Unsafe source-codec replacement, integer truncation and missing NULL handling
mutations fail and are reverted. Focused coverage: **115 passed**. Full local
suite: **4,017 passed**, exit 0, 1160.66s. Static/CI status is recorded in the PR.
No private-call-count or speed assertions enter CI.

Initial test preflight incorrectly expected a one-field select to return tuples;
corrected to scalar results before final baseline/candidate runs. Failed preflight
logs are retained, not counted as validation or timing evidence. The benchmark
profile preflight passed all four workloads before implementation.

Published **1,140 samples**:

- [288 primary timings](results/derived-sum-512/timing-trials.csv),
  [120 forward](results/derived-sum-512/forward-trials.csv),
  [120 reverse](results/derived-sum-512/reverse-trials.csv),
  [240 pinned controls](results/derived-sum-512/pinned-trials.csv),
  [120 unpinned target](results/derived-sum-512/target-unpinned-trials.csv),
  [120 pinned target](results/derived-sum-512/target-pinned-trials.csv),
  [24 memory](results/derived-sum-512/memory-trials.csv), and
  [probe commands/provenance](results/derived-sum-512/probe-manifest.json).
- [108 comparative trials](results/derived-sum-512/comparative-trials.csv) and
  [environment/session/command metadata](results/derived-sum-512/comparative-manifest.json).

Full validation preceded timings. Owned timing/memory/profiles/follow-ups ran
sequentially, with clean source trees and zero exits. Raw evidence:
`/home/crpier/.cache/snekql-512/`; discovery/mutations:
`/home/crpier/.cache/snekql-derived-sum-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled runs pin to CPU 2. No exclusive host control;
visible-test checks cannot prevent other sessions starting mid-measurement.

## Reproduction

Same dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, private disk-backed `TMPDIR`.
Save scripts outside source roots; run from exact revision worktrees. Primary:
six B/C alternating processes. Memory/profile modes run separately. After each
primary process, run the independent comparative command:

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
                key=Metric.id.sum(),
                units=Metric.units.sum(),
                amount=Metric.amount.sum(),
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
        fields = (key.sum(), units, amount)
        group = (key, units, amount)
    else:
        fields = (key.sum(), units.sum(), amount.sum())
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

C/B alternating phases 0–5, importing the same `probe.py`.

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

### Target repeats

Copy `pinned.py` to `target.py` and replace the workload tuple with `("one",)`.
Run C/B alternating phases 0–5 with `python target.py PHASE_INDEX`, then separately
with `taskset -c 2 python target.py PHASE_INDEX`. Keep the series separate.
