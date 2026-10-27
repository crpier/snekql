# Retaining resolved numeric classification — #514

Measured 2026-10-23 (UTC). Clean baseline `a6db153` (merged #513), initial candidate
`6a997f4`, revised implementation **`4330c32`**. Incremental gains, not multiplied
historical results. All initial and revised samples are retained separately.

## Change and rejected layout

The retained derived-SUM numeric gate repeatedly decomposed the same resolved
logical annotation. Keep every gate and source `.sum()` call, but retain the
classification **only when the existing resolved-annotation cache proves the
annotation fully resolved**. Unknown/unbound/forward declarations retry. Boolean
exclusion, nullable/annotated numeric domains, alias/FK semantics and validation
remain. No global/class capability cache, SQL rewrite, API or driver changes.

The first layout added a separate descriptor attribute. Memory measurements
rejected it: unbound descriptors grew **328.85 → 1,913.62 bytes/item** and a
three-column declaration **7,937.80 → 12,687.64 bytes/model** (~60%). This is
consistent with crossing a Python shared-dictionary layout threshold; the
measurements, not a claim about every interpreter, justify rejecting it.

The final layout stores classification as the second item of the existing
resolved-annotation tuple. No extra descriptor dictionary key. Tuple entries are
immutable; aliases retain source meaning. Classification is still populated only
on numeric use. The resolved tuple is one item larger even for nonnumeric columns.
Full validation and every measurement were repeated after this refinement.

## Final wide buffered SQLite results

2,000 rows `(id, units, amount) = (n, 2*n, n/2)`, private disk-backed database,
prebuilt queries/shared transactions, three optional named-result fields. Six
fresh B/C alternating processes, six trials of 100 reads after ten warmups:
**18 samples/workload/revision**. Check row count and endpoint values on every read.

Each read returns 1,000 rows/singleton groups. One-derived-SUM groups by all three
CTE outputs, summing key and projecting units/amount. Three-derived-SUM sums all
three outputs grouped by key. Physical control sums all three physical columns.

| Workload | Baseline reads/s | Final reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection | 328.47 | 328.66 | 1.001× |
| Physical SUM control | 445.95 | 443.51 | 0.995× |
| One derived SUM | 242.68 | 282.24 | **1.163×** |
| Three derived SUMs | 190.70 | 266.43 | **1.397×** |

These are targeted buffered SQLite gains, not MariaDB/streaming or universal SQL
throughput claims. Large input groups, SQL-heavy queries and other domains differ.

## Single-row evidence and controls

Primary one-row protocol: six 2,000-operation trials after 200 warmups per process.
Longer ordinary controls in both revision orders and CPU-2-pinned ordinary/physical
SUM controls were scheduled before observing results: six processes, ten
5,000-read trials after 1,000 warmups (**30 samples/combination/revision**).
Adapter/workload order rotates. Raw consumes the same compiled SQL/bindings and
strict named result model, not the full snekql runtime contract.

| Final primary | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary | 12,167 | 11,941 |
| Physical SUM | 9,526 | 9,627 |
| One derived SUM | 7,848 | 8,052 |
| Three derived SUMs | 7,950 | 8,231 |

| Final ordinary follow-up | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 11,997 | 12,203 |
| Unpinned B/C | raw | 30,908 | 31,703 |
| Unpinned C/B | snekql | 11,542 | 12,247 |
| Unpinned C/B | raw | 31,420 | 31,604 |
| Pinned C/B | snekql | 12,244 | 12,185 |
| Pinned C/B | raw | 34,499 | 34,618 |

Pinned physical SUM: **9,587 → 9,565** snekql / **34,357 → 34,391** raw. Main-thread
CPU: ordinary **74.670 → 75.026 µs/read**, physical SUM **96.619 → 96.865 µs/read**.
Small pinned decreases and the primary ordinary decrease are retained, not
explained away by raw ratios. Pinning is not exclusive host control or causal
isolation. Do not claim general point-read improvement or blanket non-regression.

Independent standard-fixture comparative runs follow each primary process after
its database closes: per-operation query construction, per-read transaction, six
rotating adapter trials of 2,000 operations after 200 warmups. Final medians:

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,476 | 14,373 |
| snekql | 3,384 | 3,365 |
| SQLAlchemy | 3,211 | 3,253 |

## Memory: output and declaration costs separately

Final tracemalloc retains 20 reads × 1,000 rows, three samples/workload/revision:

| Workload | Retained bytes, B → C | Peak bytes, B → C |
| --- | ---: | ---: |
| Ordinary | 10,894,441 → 10,894,441 | 10,970,305 → 10,970,305 |
| Physical SUM | 10,894,470 → 10,894,470 | 10,971,246 → 10,971,246 |
| One derived SUM | 10,894,619 → 10,894,619 | 10,971,155 → 10,970,843 |
| Three derived SUMs | 10,894,654 → 10,894,654 | 10,971,462 → 10,971,150 |

Output retention is unchanged; peaks approximately unchanged. This alone cannot
measure declaration metadata. Separate declaration probes retain either 3,000
unbound integer descriptors or 200 three-column models (cold or after SUM/AVG
construction), after 30 warmup builds. Three trials/process, six B/C alternating
processes: **nine samples/case/revision**.

| Final declaration probe | Baseline bytes/item | Candidate bytes/item |
| --- | ---: | ---: |
| Unbound descriptor | 328.87 | 328.83 |
| Three-column declared model | 7,943.38 | 7,964.37 |
| Same model, numeric gates warmed | 7,979.77 | 8,003.75 |

Final cost is about **21–24 bytes per three-column model** (~0.3%), consistent with
one extra tuple item per resolved column, not the initial ~4.75 KB increase.
Unbound retention is unchanged. These are traced retained allocations, not RSS or
isolated constructor latency; peak/setup samples are also published. This cache
has a declaration-memory cost even when queries never benefit from it.

## Profiles: retain gates, remove decomposition

Final three-derived-SUM profiles consume 100 × 1,000 rows separately from timing.

| Count | Baseline → Final |
| --- | ---: |
| `_annotation_core_types` | **300,000 → 0** |
| `_logical_is_numeric` | 300,000 → 300,000 |
| `_require_numeric_aggregate` | 300,000 → 300,000 |
| Source `.sum()` | 300,000 → 300,000 |
| Provenance `require_numeric_source` | 300,000 → 300,000 |
| `_normalize_sum` | 300,000 → 300,000 |
| Named-result materializations | 100,000 → 100,000 |

The cache is warmed before profiling, as it is during ordinary query construction.
These counts corroborate avoided classification work, not skipped gates or numeric
conversions. Profile durations are not throughput estimates.

## Initial candidate: retained, not shipped as the final layout

Initial wide reads/s, B → C: ordinary **314.70 → 325.98**, physical SUM
**422.52 → 449.08**, one derived SUM **238.23 → 272.80**, three **184.07 → 259.56**.
Initial one-row ordinary **8,786 → 8,666**, physical **7,705 → 6,158**, one derived
SUM **6,537 → 5,790**, three **5,885 → 6,576**. These mixed results belong to the
rejected descriptor layout and are not pooled with the revised candidate.

Initial longer ordinary B/C: snekql **9,619 → 8,662**, raw **27,729 → 23,575**;
C/B: snekql **8,993 → 9,971**, raw **26,501 → 27,646**. Initial pinned ordinary
**12,050 → 12,191**, physical **9,504 → 9,527**. Initial comparative raw
**12,198 → 11,902**, snekql **2,652 → 3,084**, SQLAlchemy **2,779 → 2,966**.
All initial timing, raw controls, CPU and memory samples remain published. Neither
layout changes nor affinity fully explain host variation; final baseline differs
from initial baseline, so do not compare candidate-only rates across series.

## Validation and provenance

Three new public compiler-seam tests pass on baseline and both candidates:
retry a provisional forward-annotation rejection; do not preserve an unbound
guess after text binding; retain warmed per-column/alias/deferred-FK numeric
semantics, boolean rejection and write validation. Existing public derived-SUM
SQLite/MariaDB buffered/streamed coverage remains in the focused set. No speed or
private-call-count assertions enter tests.

Provisional caching, unbound caching, bool acceptance and blocked frozen-cache
population mutations fail on both layouts and are reverted. Focused **79 passed**.
Initial full suite **4,020 passed**, 1028.75s. Final first full attempt:
**4,019 passed / one error**, 1028.32s, at migration test
`backslash_ending_identifier_cannot_hide_commit[backslash]`, during initialization
with a 10 ms connection-acquisition timeout. The unchanged migration file then
passed **28 cases on baseline and candidate**. A complete final rerun passed
**4,020 tests**, exit 0, 882.55s. The failure log remains; targeted repeats alone
were not treated as clean full validation. Static/CI status is recorded in the PR.

The first new-test preflight assumed an unresolved numeric annotation was
permissive. Baseline actually rejected that forward annotation. The test was
corrected to assert the early rejection and later successful numeric resolution,
before final baseline/candidate validation. Failed preflight logs are retained.

Published **1,908 samples**, 954 for each layout: 288 primary timings, 120 forward,
120 reverse, 240 pinned, 24 output memory, 54 declaration memory, 108 comparative.

- [Initial data](results/numeric-classification-514/initial/probe-manifest.json):
  [timing](results/numeric-classification-514/initial/timing-trials.csv),
  [forward](results/numeric-classification-514/initial/forward-trials.csv),
  [reverse](results/numeric-classification-514/initial/reverse-trials.csv),
  [pinned](results/numeric-classification-514/initial/pinned-trials.csv),
  [output memory](results/numeric-classification-514/initial/memory-trials.csv),
  [declaration memory](results/numeric-classification-514/initial/setup-trials.csv),
  [comparative](results/numeric-classification-514/initial/comparative-trials.csv),
  [comparative provenance](results/numeric-classification-514/initial/comparative-manifest.json).
- [Final data](results/numeric-classification-514/final/probe-manifest.json):
  [timing](results/numeric-classification-514/final/timing-trials.csv),
  [forward](results/numeric-classification-514/final/forward-trials.csv),
  [reverse](results/numeric-classification-514/final/reverse-trials.csv),
  [pinned](results/numeric-classification-514/final/pinned-trials.csv),
  [output memory](results/numeric-classification-514/final/memory-trials.csv),
  [declaration memory](results/numeric-classification-514/final/setup-trials.csv),
  [comparative](results/numeric-classification-514/final/comparative-trials.csv),
  [comparative provenance](results/numeric-classification-514/final/comparative-manifest.json).

Owned tests/timings/memory/profiles ran sequentially. All measured source trees
were clean; measurement commands exited zero. Raw evidence:
`/home/crpier/.cache/snekql-514/`, `/home/crpier/.cache/snekql-514-final/`; tests and
discovery: `/home/crpier/.cache/snekql-numeric-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled follow-ups pin CPU 2; no exclusive host control.

## Reproduction

Same dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1`, private disk-backed `TMPDIR`.
Keep scripts outside source roots and run from exact revision worktrees. Repeat
all phases separately for the initial and final candidates. Save each raw JSON.

Six primary B/C alternating processes; memory/profile modes separately. Following
each primary timing process, run the independent comparative command:

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

Keep beside `probe.py`. Phases 0–5, B/C alternating then separately C/B alternating.

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

C/B alternating phases 0–5; import the same `probe.py`.

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

### Declaration memory: `python setup.py`

Six B/C alternating fresh processes, separate from timings.

```python
import gc, json, os, subprocess, sys, tracemalloc

sys.path.insert(0, os.getcwd())
from typing import ClassVar
from snekql import sqlite


def model():
    class Metric[S = sqlite.Pending](sqlite.Model[S]):
        __row_type__: ClassVar[sqlite.ReadType[Metric[sqlite.Row]]]
        key: sqlite.Col[int] = sqlite.Integer(primary_key=True)
        units: sqlite.Col[int | None] = sqlite.Integer(default=None)
        amount: sqlite.Col[float] = sqlite.Real()

    return Metric


def build(kind):
    if kind == "unbound":
        return sqlite.Integer()
    m = model()
    if kind == "warmed":
        for col in (m.key, m.units, m.amount):
            col.sum()
            col.avg()
    return m


samples = []
for kind in ("unbound", "declared", "warmed"):
    for _ in range(30):
        build(kind)
    for trial in range(3):
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        count = 3000 if kind == "unbound" else 200
        held = [build(kind) for _ in range(count)]
        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples.append(
            dict(
                shape=kind,
                trial=trial + 1,
                count=count,
                retained_bytes=current - before,
                peak_bytes=peak - before,
                retained_bytes_per_item=(current - before) / count,
            )
        )
        del held
print(
    json.dumps(
        dict(
            commit=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            dirty=bool(
                subprocess.check_output(["git", "status", "--porcelain"], text=True)
            ),
            samples=samples,
        )
    )
)
```
