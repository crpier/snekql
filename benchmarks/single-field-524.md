# Direct single-field SELECT materialization — #524

Measured 2026-10-24 UTC. Clean baseline **`acb1649`** (merged #523) versus candidate
**`f831bee`**. Incremental evidence; do not multiply historical gains.

## Change and retained contracts

After the existing row-width check and whole-source/join handling, single-field
SELECT projections call their resolved decoder directly rather than building a
zip, generator and decoded tuple. Scalar results return that actual value,
including collection-valued and NULL results. A named one-field result still
receives a one-element tuple and passes through final contract validation.

Decoders, extension precedence, validation policy, SQL, cardinality, transaction
ownership, error boundaries, driver execution and checkpoints are unchanged.
Whole-model/joined model branches remain first. RETURNING is unchanged. Multi-field
projections keep the general decode iteration, with an extra width condition;
that branch cost is not assumed free. No new cache, persistent field, per-plan
strategy object, public API or dependency/driver change.

## Wide buffered SQLite reads

Private disk-backed SQLite with 2,000 `(id, units, amount) = (n, 2*n, n/2)` rows.
Prebuilt queries/shared transaction, ordered by key and limited by key predicate.
Six alternating B/C processes; six trials × 100 reads after ten warmups for
1,000-row reads: **18 samples/workload/revision**. Each read consumes every row
and checks count/endpoint values.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Three-field named control | 331.54 | 331.06 | 0.999× |
| Three-field tuple control | 524.81 | 539.21 | 1.027× |
| Single integer scalar | 1,014.13 | 1,499.41 | **1.479×** |
| Single integer named result | 520.85 | 625.92 | **1.202×** |

Target gains align with removed single-field iteration. Controls differ, so do
not normalize against them or attribute every difference to the patch. These
are buffered SQLite integer projections, not all single-field types, MariaDB,
streaming or general query throughput. Other shapes perform different required
work; cross-shape throughput is not an optimization gain.

## One-row results and adverse controls

Primary one-row trials: six × 2,000 reads after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Three-field named | 9,448 | 10,597 |
| Three-field tuple | 11,649 | 11,600 |
| Single integer scalar | 13,110 | 12,823 |
| Single integer named | 10,608 | 10,658 |

The target scalar's primary decline is retained. Longer three-field named controls
were scheduled before primary results: six processes, ten × 5,000 reads after
1,000 warmups, rotating adapter order, **30 samples/adapter/revision**. Forward
B/C and reverse C/B are separate unpinned series; pinned C/B uses CPU 2. Raw runs
identical compiled SQL and strictly validates the named result model, not the
whole snekql runtime contract.

| Three-field named series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 9,537 | 9,471 |
| Unpinned B/C | raw | 29,137 | 28,588 |
| Unpinned C/B | snekql | 10,554 | 9,301 |
| Unpinned C/B | raw | 28,261 | 28,992 |
| Pinned C/B | snekql | 12,142 | 12,086 |
| Pinned C/B | raw | 34,379 | 34,454 |

The **~12% snekql decline in the unpinned C/B series remains unexplained**, with
raw moving upward. Main-thread CPU µs/read there: **88.803 → 100.356**. Pinned
snekql CPU **75.249 → 75.580**, raw **19.365 → 19.357**; the smaller pinned
throughput decline is ~0.5%. Added multi-field width branching is real, but its
share of these changes is not isolated. Do not pool series, normalize by raw,
or treat affinity as proof that adverse results do not matter.

### Dedicated scalar one-row repeats

Scheduled after the initial results, using the same longer protocol, B/C
alternation. Raw consumes the same single-column SQL and validates the value
through a prebuilt integer `TypeAdapter` (not the entire runtime contract).

| Scalar repeat | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 14,158 | 14,071 |
| Unpinned B/C | raw | 32,639 | 31,786 |
| Pinned B/C | snekql | 14,458 | 14,625 |
| Pinned B/C | raw | 36,063 | 36,074 |

Scalar CPU µs/read: unpinned **65.434 → 65.807**, pinned
**62.620 → 61.832**. The unpinned target still declined slightly; the pinned
target improved. No isolated general point-read or blanket non-regression claim,
and no causal explanation established for the large unpinned control decline.

Independent comparative point reads build queries and use per-read transactions
with the standard fixture, after each primary process closes its database. Six
rotating adapter trials × 2,000 reads after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,771 | 12,312 |
| snekql | 2,958 | 2,992 |
| SQLAlchemy | 3,035 | 3,027 |

## Retention and allocation

Separate tracemalloc probes retain 20 reads × 1,000 rows, three trials per
shape/revision. Traced output/peak allocations are not process RSS or native
worker-buffer memory. No new persistent cache or plan field; the named target
still needs its one-element values tuple. Setup and existing decoder binding are
not eliminated by avoiding per-row iteration.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Three-field named | 10,894,441 → 10,894,441 | 10,970,321 → 10,970,321 |
| Three-field tuple | 2,413,689 → 2,413,689 | 2,424,707 → 2,424,707 |
| Single integer scalar | 186,790 → 186,790 | 252,773 → 252,661 |
| Single integer named | 10,106,801 → 10,106,801 | 10,166,481 → 10,166,481 |

Retention unchanged; peaks flat/slightly lower. These result contracts have
very different allocation requirements, including native small-integer sharing.
The scalar workload's low retention must not be generalized to arbitrary values
or described as a before/after gain.

## Diagnostic profiles

Separate profiles: 100 reads × 1,000 rows per shape.

| Call count | Baseline → Candidate |
| --- | ---: |
| Scalar per-row decode-generator resumptions | **200,000 → 0** |
| Named single-field decode-generator resumptions | **200,000 → 0** |
| Scalar column decodes | 100,000 → 100,000 |
| Named single-field column decodes | 100,000 → 100,000 |
| Named single-field final materializations | 100,000 → 100,000 |
| Either three-field control's generator resumptions | 400,000 → 400,000 |
| Either three-field control's column decodes | 300,000 → 300,000 |

Generator counts include final exhaustion. Profiles corroborate avoided
iteration without bypassing codecs/validation; profile times are not throughput.

## Validation and provenance

Eight new public transaction cases pass on baseline and candidate:

- SQLite/MariaDB buffered, streamed and `fetch_one` results preserve a decoded
  collection as one scalar value; a named single-field contract remains a model
  and runs its final transformation exactly once.
- Buffered/streamed policy extensions retain False/True/False validation reuse;
  missing LEFT-join values remain NULL; one-field named validator failures still
  raise `ModelValidationError`. Subsequent reads remain usable.
- Nullable scalar values and whole-model singleton-column results retain their
  distinct shapes; whole-model rows remain frozen.

Unsafe mutations caught/restored: bypass decoder **8 failures**, bypass named
contract **6 failures/2 errors**, wrap scalar value as a tuple **8 failures**.
**83 focused cases pass**, including existing source policies, derived/scalar
NULL contexts, named contracts and whole-model/joined shapes.

Full suite **4,073 passed**, exit 0, **1058.46s**. Ruff/format/ty/whitespace pass;
CI status is tracked in the PR. Tests assert public behavior, not private call
counts or speed. No failed/cancelled benchmark samples discarded. Owned tests,
timings, profiles and memory probes ran sequentially on clean measured revisions.

Published **1,020 samples**: 288 primary, 120 forward, 120 reverse, 120 pinned,
120 scalar-unpinned, 120 scalar-pinned, 24 memory and 108 comparative trials.

- [Probe commands/metadata](results/single-field-524/probe-manifest.json)
- [Primary timing](results/single-field-524/timing-trials.csv)
- [Forward named control](results/single-field-524/forward-trials.csv)
- [Reverse named control](results/single-field-524/reverse-trials.csv)
- [Pinned named control](results/single-field-524/pinned-trials.csv)
- [Unpinned scalar repeat](results/single-field-524/target-unpinned-trials.csv)
- [Pinned scalar repeat](results/single-field-524/target-pinned-trials.csv)
- [Memory](results/single-field-524/memory-trials.csv)
- [Comparative trials](results/single-field-524/comparative-trials.csv)
- [Comparative provenance](results/single-field-524/comparative-manifest.json)

Raw evidence: `/home/crpier/.cache/snekql-524/`; discovery/tests/mutations:
`/home/crpier/.cache/snekql-single-next/`.

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


class Single(BaseModel):
    value: int


class Role:
    pass


def query(width, shape):
    if shape == "scalar":
        return (
            sqlite.select(Metric.id)
            .where(Metric.id.lte(width))
            .order_by(Metric.id.asc())
        )
    if shape == "tuple":
        return (
            sqlite.select(Metric.id, Metric.units, Metric.amount)
            .where(Metric.id.lte(width))
            .order_by(Metric.id.asc())
        )
    q = sqlite.select(Metric).where(Metric.id.lte(width)).order_by(Metric.id.asc())
    if shape == "single-named":
        return q.project(Single, value=Metric.id)
    return q.project(Record, key=Metric.id, units=Metric.units, amount=Metric.amount)


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
                for shape in ("plain", "tuple", "scalar", "single-named"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width

                        def value(row):
                            if shape == "scalar":
                                return row
                            if shape == "single-named":
                                return row.value
                            if shape == "tuple":
                                return row
                            return (row.key, row.units, row.amount)

                        assert value(rows[0]) == (
                            1 if shape in ("scalar", "single-named") else (1, 2, 0.5)
                        )
                        assert value(rows[-1]) == (
                            width
                            if shape in ("scalar", "single-named")
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

### Named controls: `python followup.py PHASE_INDEX`

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

### Pinned named control: `taskset -c 2 python pinned.py PHASE_INDEX`

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
            for shape in ("plain",):
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

### Scalar repeats: `python target.py PHASE_INDEX`

Phases 0–5, B/C alternation, then separately repeat with `taskset -c 2`.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from pydantic import TypeAdapter
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
            q = query(1, "scalar")
            compiled = q.compile()
            native_validator = TypeAdapter(int)

            async def snekql_read():
                rows = await tx.fetch_all(q)
                assert len(rows) == 1
                assert rows == [1]

            async def raw_read():
                async with raw.execute(compiled.sql, compiled.params) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
                row = native_validator.validate_python(rows[0][0], strict=True)
                assert row == 1

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
