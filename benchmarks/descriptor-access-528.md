# Inherited runtime column access — #528

Measured 2026-10-24 UTC. Clean baseline **`7222b74`** (merged #527) versus candidate
**`44b4967`**. Incremental evidence; do not multiply historical gains.

## Candidate and scope

`FKAttr.__get__` and MariaDB `JsonAttr.__get__` specialize static descriptor
signatures, but their runtime implementations only call `super().__get__` with
two no-op typing casts. Keep these declarations under `TYPE_CHECKING`, allowing
runtime access to inherit the ordinary descriptor implementation directly.

Class access still returns the descriptor, preserving column/FK/JSON operations;
instance access still reads the actual stored logical value. Custom descriptor
overrides and `super()` delegation, setters, freezing, pending/generated values,
SQL, codecs, validation and runtime policies are not bypassed. Static overloads
remain available to the type checker; no new cache, persistent model/plan field,
public API or dependency change. Runtime lookup no longer has distinct delegating
functions on the specialized classes; function identity/overload introspection
is not the preserved contract.

Discovery came from a joined-result profile with **600,600 wrapper calls** while
consuming 100 × 1,000 two-model rows. Much of that cost was the benchmark reading
model attributes, **not SQL execution or fetched-row materialization**. The
measurements below explicitly separate value access from database throughput.

## Already-loaded value access

Preload 1,000 three-field rows from SQLite before timing. Each scan reads and sums
all three values, checking a checksum of **1,751,750**. No database I/O or model
construction occurs inside the scan loop. Six alternating B/C processes; six
rotating workload trials each: **18 samples/workload/revision**.

| Workload | Unit | Baseline | Candidate | Ratio |
| --- | --- | ---: | ---: | ---: |
| Model values | 1,000-row scans/s | 2,456.84 | 3,706.99 | **1.509×** |
| Named Pydantic values, control | 1,000-row scans/s | 17,699.50 | 17,697.49 | 1.000× |
| Three class-side column accesses | triplets/s | 3,980,283 | 9,515,349 | **2.391×** |
| Construct filtered/ordered model SELECT | queries/s | 105,492.58 | 105,386.47 | 0.999× |

Value scans: 2,000 operations/trial after 100 warmups. Class accesses: 200,000
triplets after 10,000 warmups, retaining identity checks. Construction: 10,000
queries after 1,000 warmups; creates SELECT/WHERE/ORDER BY, does not compile or
execute. Control contracts differ; their absolute rates are not competing
implementations or cross-shape optimization gains.

Evidence supports faster **column access** for this fixture. It does not support
a construction gain or claim that database reads are 51% faster. These scans use
SQLite-loaded integer/real fields; MariaDB JSON behavior is tested, not given a
separate throughput claim.

## Buffered SQLite database reads

Private disk-backed 2,000-row fixture `(id, units, amount) = (n, 2*n, n/2)`.
Prebuilt queries/shared transaction, key predicate and ordering. Six alternating
B/C processes, six × 100 reads after ten warmups for 1,000-row reads. Each fetch
buffers every result and checks count/endpoint values. `consume` additionally
scans all three attributes on every result and checks the checksum.

| Workload, 1,000 rows/read | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Model fetch, endpoint checks only | 344.69 | 330.54 | 0.959× |
| Named fetch, endpoint checks only | 302.64 | 321.84 | 1.063× |
| Model fetch plus full value scan | 299.53 | 312.89 | 1.045× |
| Named fetch plus full value scan | 301.22 | 305.06 | 1.013× |

The model fetch-plus-consume path improved ~4.5%, but fetch-only model throughput
**declined ~4.1%** and named controls also moved. The standalone access evidence
is cleaner; **no isolated database-throughput gain or blanket non-regression
claim**. No MariaDB/streaming/bulk-write speed claim or raw normalization.

### One-row and longer controls

Primary point trials: six × 2,000 reads after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Model fetch | 10,803 | 11,389 |
| Named fetch | 9,474 | 10,386 |
| Model fetch plus consume | 10,224 | 10,561 |
| Named fetch plus consume | 9,007 | 9,711 |

Longer named-read controls were scheduled before primary results: six processes,
ten × 5,000 reads after 1,000 warmups, rotating adapter order, **30 samples per
adapter/revision**. B/C and C/B are separate unpinned series; pinned C/B uses CPU
2. Raw executes identical compiled SQL and strictly validates its named result,
not the complete runtime contract.

| Named-read series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 9,394 | 9,217 |
| Unpinned B/C | raw | 27,295 | 27,211 |
| Unpinned C/B | snekql | 8,728 | 9,031 |
| Unpinned C/B | raw | 24,788 | 25,369 |
| Pinned C/B | snekql | 11,921 | 11,934 |
| Pinned C/B | raw | 33,846 | 33,444 |

Pinned main-thread CPU µs/read: snekql **76.643 → 76.521**, raw
**19.699 → 19.887**. The forward decline/reverse increase and nearly flat pinned
result do not isolate a point-read effect or explain all primary movements.
Affinity does not prove that adverse results are irrelevant.

Independent comparative point reads build queries and use per-read transactions
with the standard fixture after each primary database closes: six rotating
adapter trials × 2,000 reads after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 12,575 | 10,639 |
| snekql | 2,815 | 2,591 |
| SQLAlchemy | 2,830 | 2,286 |

All declined, including snekql by ~8%. Results remain published; do not normalize
by other adapters, pool unlike series or claim these changes are causally
explained by scheduling. No exclusive host control.

## Memory and setup

Separate tracemalloc probes retain 20 reads × 1,000 rows, three trials per shape
and revision. Traced outputs/peaks, not RSS/native buffers/import memory.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Model fetch | 4,494,409 → 4,494,409 | 4,571,953 → 4,571,953 |
| Named fetch | 10,894,441 → 10,894,441 | 10,970,329 → 10,970,329 |
| Model fetch + consume | 4,494,409 → 4,494,409 | 4,571,953 → 4,571,953 |
| Named fetch + consume | 10,894,441 → 10,894,441 | 10,970,329 → 10,970,329 |

No observed output/peak change. No new per-model or execution-local stored
strategy. Specialized wrapper/overload declarations are no longer executed at
runtime; import/startup latency or memory was **not isolated**, so no quantified
startup gain is claimed. Existing metadata and validation setup remain.

## Diagnostic profiles

Separate model-fetch-plus-consume profile, 100 × 1,000 rows. Reads include six
endpoint accesses per operation as well as three accesses per consumed row.

| Call count | Baseline → Candidate |
| --- | ---: |
| Delegating FK descriptor getter | **300,600 → 0** |
| Base descriptor getter | 300,600 → 300,600 |
| `typing.cast`, total | **1,404,200 → 803,000** |
| Column decodes | 300,000 → 300,000 |
| Pydantic adapter validation | 300,000 → 300,000 |
| Model attribute assignments | 300,000 → 300,000 |
| Descriptor assignments | 300,000 → 300,000 |

Two no-op casts disappear per wrapper call, not codecs or field access.
Profile times are diagnostic and are not throughput measurements.

## Validation and provenance

Six new public transaction/model cases pass baseline/candidate:

- SQLite/MariaDB buffered/streamed joined rows retain callable nullable FK
  binding and class-side `references`; Pending/returned/fetched values retain a
  custom descriptor's `super()` behavior. Normal encoding observes the getter;
  scalar projections observe persisted values. Pending and Row remain frozen.
- MariaDB JSON class-side operators still execute, and loaded collection access
  returns the actual logical collection rather than copying/re-decoding it.
  Nested list mutability and frozen attribute assignment remain distinct.

Unsafe mutations caught/restored: integer getter alteration **4 failures**,
collection-copy getter **2 failures**, class access returning None **6 errors**.
Removing the static specialization declarations yields **99 ty diagnostics**;
restoring them passes. Existing positive/negative typing corpus remains intact.
**50 focused passed**; full suite **4,085 passed**, exit 0, **1006.70s**.
Ruff/format/ty/whitespace pass; CI status is tracked in the PR.

Test preflights: callable FKs required explicit Python defaults (set to None);
a frozen assignment needed an intentional test-side Any cast. One mutation
command exceeded its 30-second tool budget after reporting all six expected
class-access errors; the source was manually restored and focused/full checks
passed afterward. Logs retained. No failed/cancelled benchmark samples discarded.

Owned tests, throughput, profiles and memory ran sequentially on clean measured
revisions. Other development activity was observed on this shared host; runners
waited for detected test jobs before measurements, without controlling unrelated
activity. No private call-count or speed assertions in CI.

Published **924 samples**: 144 access/construction, 288 primary database timing,
120 forward, 120 reverse, 120 pinned, 24 memory, 108 comparative.

- [Probe metadata/commands](results/descriptor-access-528/probe-manifest.json)
- [Access/construction](results/descriptor-access-528/access-trials.csv)
- [Database timing](results/descriptor-access-528/timing-trials.csv)
- [Forward control](results/descriptor-access-528/forward-trials.csv)
- [Reverse control](results/descriptor-access-528/reverse-trials.csv)
- [Pinned control](results/descriptor-access-528/pinned-trials.csv)
- [Memory](results/descriptor-access-528/memory-trials.csv)
- [Comparative trials](results/descriptor-access-528/comparative-trials.csv)
- [Comparative provenance](results/descriptor-access-528/comparative-manifest.json)

Raw evidence `/home/crpier/.cache/snekql-528/`; tests/mutations
`/home/crpier/.cache/snekql-descriptor-next/`; initial profile
`/home/crpier/.cache/snekql-joined-spans-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F/28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled follow-ups pin CPU 2.

## Reproduction

Exact clean revisions/identical dependencies, private disk-backed `TMPDIR`,
`PYTHON_CONTEXT_AWARE_WARNINGS=1`; scripts outside worktrees. Six fresh B/C
processes alternating three times; save stdout JSON. For each process run access,
primary timing and then comparative separately. Memory/profiles separately:

```bash
python -m benchmarks.compare --backend sqlite --workload point-read \
    --rows 2000 --operations 2000 --trials 6 --warmup 200
```

### Database probe: `python probe.py timing`, `memory` or `profile`

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
    q = sqlite.select(Metric).where(Metric.id.lte(width)).order_by(Metric.id.asc())
    return (
        q
        if shape.startswith("model")
        else q.project(Record, key=Metric.id, units=Metric.units, amount=Metric.amount)
    )


def checksum(rows, named):
    if named:
        return sum(row.key + row.units + row.amount for row in rows)
    return sum(row.id + row.units + row.amount for row in rows)


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
                    "model-consume",
                    "named-consume",
                ):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width

                        def values(row):
                            return (
                                row.key if shape.startswith("named") else row.id,
                                row.units,
                                row.amount,
                            )

                        assert values(rows[0]) == (1, 2, 0.5)
                        assert values(rows[-1]) == (width, 2 * width, width / 2)
                        if shape.endswith("consume"):
                            assert (
                                checksum(rows, shape.startswith("named"))
                                == 3.5 * width * (width + 1) / 2
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

### Access/construction: `python access.py`

Keep beside `probe.py`; loading/setup occurs outside timed operations.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from probe import Metric, query, seed, sqlite, checksum


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "access.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
        ):
            models = await tx.fetch_all(query(1000, "model-read"))
            named = await tx.fetch_all(query(1000, "named-read"))

            def model_values():
                assert checksum(models, False) == 1751750.0

            def named_values():
                assert checksum(named, True) == 1751750.0

            columns = (Metric.id, Metric.units, Metric.amount)

            def class_columns():
                assert (
                    Metric.id is columns[0]
                    and Metric.units is columns[1]
                    and Metric.amount is columns[2]
                )

            def construction():
                return query(1, "model-read")

            work = [
                ("model-values", model_values, 2000, 100),
                ("named-values", named_values, 2000, 100),
                ("class-columns", class_columns, 200000, 10000),
                ("construction", construction, 10000, 1000),
            ]
            for _, op, _, warmup in work:
                for _ in range(warmup):
                    op()
            for trial in range(6):
                shift = trial % 4
                for shape, op, operations, _ in work[shift:] + work[:shift]:
                    cpu = time.thread_time()
                    start = time.perf_counter()
                    for _ in range(operations):
                        op()
                    elapsed = time.perf_counter() - start
                    cpu_elapsed = time.thread_time() - cpu
                    samples.append(
                        dict(
                            shape=shape,
                            trial=trial + 1,
                            operations=operations,
                            seconds=elapsed,
                            main_thread_cpu_seconds=cpu_elapsed,
                            ops_s=operations / elapsed,
                        )
                    )
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

### Longer controls: `python followup.py PHASE_INDEX`

Keep beside `probe.py`, phases 0–5, B/C then separately C/B.

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

Phases 0–5, C/B; keep beside `probe.py`.

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
