# Ordered whole-model RETURNING decoding — #522

Measured 2026-10-24 UTC. Clean baseline **`d5486ef`** (merged #521) versus candidate
**`9913b60`**. Incremental evidence; do not multiply historical gains.

## Change and contracts

Whole-model RETURNING previously built a dictionary for every row, then copied it
inside `decode_model_row` and rediscovered model metadata. It now reuses the
existing `decode_model_values` helper with the frozen ordered column mapping
resolved once per returned batch. No additional persistent cache or wrapper.

Column decoding, backend/validation policy, normal model setters/descriptors,
Row state and freezing remain. Cardinality, SQL, driver work, transaction/error
boundaries and explicit positional/named RETURNING are unchanged. The existing
read-side ordered helper is reused, not a second fast materializer or a direct
instance-storage bypass. No public API, dependency or driver changes.

## Buffered SQLite UPDATE RETURNING throughput

Private disk-backed SQLite, 2,000 `(id, units, amount) = (n, 2*n, n/2)` rows.
Prebuilt queries and a shared transaction; UPDATE sets `units = units + 0` for
keys up to the requested width. This deliberately holds data and encoding work
steady. It is **not** a durable-commit-per-operation benchmark, and no INSERT,
DELETE, MariaDB or general workload throughput improvement is claimed.

Six alternating B/C processes; six trials × 100 operations after ten warmups for
1,000-row operations: **18 samples/workload/revision**. Every operation consumes
all returned rows and checks count and endpoint values. Read controls select the
same physical payload as a table model or a three-field named application model;
positional RETURNING returns tuples from the same UPDATE.

| 1,000-row workload | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| Whole-model SELECT | 341.03 | 348.26 | 1.021× |
| Named SELECT | 332.13 | 321.86 | 0.969× |
| Whole-model UPDATE RETURNING | 311.57 | 352.87 | **1.133×** |
| Positional UPDATE RETURNING | 493.05 | 499.23 | 1.013× |

The ~13% target gain is consistent with removed metadata/mapping work. Controls
moved both ways, so not every change is attributed to the patch; no normalization
against controls. The named read decline is retained. Different result contracts
have different required work; cross-shape throughput is not an optimization gain.

## One-row and longer control evidence

Primary one-row trials use six × 2,000 operations after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Whole-model SELECT | 9,559 | 10,501 |
| Named SELECT | 9,656 | 9,376 |
| Whole-model UPDATE RETURNING | 9,968 | 10,303 |
| Positional UPDATE RETURNING | 8,942 | 9,616 |

Longer ordinary named-read controls were scheduled before seeing primary results:
six processes, ten × 5,000 reads after 1,000 warmups, rotating adapter order,
**30 samples/adapter/revision**. Forward B/C and reverse C/B are separate unpinned
series; the pinned C/B series uses CPU 2. The raw adapter consumes identical SQL
and strictly validates the same application model, but not snekql's full runtime
contract. There is no simultaneous second writer or raw/snekql lock competition.

| Series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 9,200 | 9,400 |
| Unpinned B/C | raw | 28,790 | 27,883 |
| Unpinned C/B | snekql | 9,342 | 9,771 |
| Unpinned C/B | raw | 28,734 | 29,406 |
| Pinned C/B | snekql | 12,149 | 12,141 |
| Pinned C/B | raw | 34,128 | 34,308 |

Pinned main-thread CPU µs/read: snekql **75.237 → 75.256**, raw
**19.534 → 19.392**. Longer results differ from primary named-read declines;
affinity does not establish causation or exclusive host control. The change does
not touch SELECT materialization. No general point-read, blanket non-regression
or isolated single-row write gain claim.

Independent comparative point reads build queries and use per-read transactions
with the standard fixture, after each primary process closes its database. Six
rotating adapter trials × 2,000 reads after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 12,531 | 13,479 |
| snekql | 2,924 | 2,958 |
| SQLAlchemy | 2,746 | 2,876 |

## Output retention and transient allocation

Separate tracemalloc probes retain 20 operations × 1,000 rows, three trials per
shape/revision. These measure traced output/peak allocations, not process RSS,
worker-native buffers or isolated setup latency. No persistent cache is added;
the batch-local column mapping already existed in the baseline.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Whole-model SELECT | 4,494,409 → 4,494,409 | 4,571,945 → 4,571,945 |
| Named SELECT | 10,894,441 → 10,894,441 | 10,970,321 → 10,970,321 |
| Whole-model RETURNING | 4,490,464 → 4,490,464 | 4,584,624 → 4,577,232 |
| Positional RETURNING | 2,410,464 → 2,410,464 | 2,498,200 → 2,498,200 |

Retention unchanged. Target peak is ~7.4 KB lower; different shapes' retention
is not a before/after gain. Table models, named Pydantic models and tuples have
distinct allocation contracts.

## Diagnostic profiles

Separate profiles: 100 operations × 1,000 whole-model UPDATE RETURNING rows.

| Call count | Baseline → Candidate |
| --- | ---: |
| `require_model_columns` | **100,300 → 300** |
| Mapping `decode_model_row` | **100,000 → 0** |
| Ordered `decode_model_values` | 0 → 100,000 |
| Column `decode` | 300,000 → 300,000 |
| Model `__setattr__` | 300,000 → 300,000 |
| Column descriptor `__set__` | 300,000 → 300,000 |

Mapping creation/copying is removed rather than bypassing required decoding or
assignment. Profiles corroborate the mechanism; profile timing is not throughput.

## Validation and provenance

Seven new public transaction cases pass on baseline and candidate:

- SQLite single INSERT, bulk INSERT, UPDATE and DELETE RETURNING preserve custom
  descriptors, immutable returned Rows and persisted values.
- SQLite/MariaDB bulk results preserve field order, mixed nullable/text/real
  payloads, logical-versus-storage values under False/True/False validation reuse,
  empty-batch cardinality and row freezing.
- SQLite UPDATE RETURNING logical validation failure preserves the materialization
  error boundary: the written state and transaction remain usable; later reads
  and unvalidated executions succeed.

Unsafe mutations caught/restored: bypass descriptors **4 failures**, force
validation off **3 failures**, omit final freeze **6 failures**. **81 focused
cases pass**, including existing model-read, named RETURNING, scalar validation,
server-default/generated-column and backend tests. No private call-count or
speed assertions in tests.

Full suite **4,065 passed**, exit 0, **1048.85s**. Ruff/format/ty/whitespace pass;
CI status is tracked in the PR. Initial test scaffolding incorrectly used
`mariadb.Double` (corrected to `mariadb.Real`) and iterated an `object`-typed
unvalidated result (added an explicit test-side cast). Those preflight failures
are archived, not benchmark observations. No failed/cancelled benchmark samples
were discarded. Owned tests, timings, profiles and memory probes ran sequentially.

Published **780 samples**: 288 primary, 120 forward, 120 reverse, 120 pinned,
24 memory and 108 comparative trials. All commands succeeded on clean measured
revisions.

- [Probe commands/metadata](results/model-returning-522/probe-manifest.json)
- [Primary timing](results/model-returning-522/timing-trials.csv)
- [Forward ordinary](results/model-returning-522/forward-trials.csv)
- [Reverse ordinary](results/model-returning-522/reverse-trials.csv)
- [Pinned ordinary](results/model-returning-522/pinned-trials.csv)
- [Memory](results/model-returning-522/memory-trials.csv)
- [Comparative trials](results/model-returning-522/comparative-trials.csv)
- [Comparative provenance](results/model-returning-522/comparative-manifest.json)

Raw evidence: `/home/crpier/.cache/snekql-522/`; discovery/tests/mutations:
`/home/crpier/.cache/snekql-returning-next/`.

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
    if shape in ("model-returning", "tuple-returning"):
        q = (
            sqlite.update(Metric)
            .set(Metric.units.to_expr(Metric.units.add(0)))
            .where(Metric.id.lte(width))
        )
        return (
            q.returning()
            if shape == "model-returning"
            else q.returning(Metric.id, Metric.units, Metric.amount)
        )
    q = sqlite.select(Metric).where(Metric.id.lte(width)).order_by(Metric.id.asc())
    return (
        q
        if shape == "model-read"
        else q.project(Record, key=Metric.id, units=Metric.units, amount=Metric.amount)
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
                for shape in (
                    "model-read",
                    "named-read",
                    "model-returning",
                    "tuple-returning",
                ):
                    q = query(width, shape)

                    async def read():
                        rows = (
                            await tx.execute(q)
                            if shape.endswith("returning")
                            else await tx.fetch_all(q)
                        )
                        assert len(rows) == width

                        def values(row):
                            if shape == "tuple-returning":
                                return row
                            return (
                                row.key if shape == "named-read" else row.id,
                                row.units,
                                row.amount,
                            )

                        assert values(rows[0]) == (1, 2, 0.5)
                        assert values(rows[-1]) == (width, 2 * width, width / 2)
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
The `plain` selector maps to the same named SELECT control as `named-read`.

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

### Pinned control: `taskset -c 2 python pinned.py PHASE_INDEX`

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
