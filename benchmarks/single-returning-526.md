# Direct single-field RETURNING materialization — #526

Measured 2026-10-24 UTC. Clean baseline **`7046c4b`** (merged #525) versus candidate
**`719ff3c`**. Incremental evidence; do not multiply historical gains.

## Change and retained contracts

Explicit single-field RETURNING selects a dedicated loop once per batch after
resolving the existing decoders. Each row retains its width assertion and column
decode, but avoids zip/generator/decoded-tuple iteration. Scalar results return
the actual decoded value, including collections/NULL. Named single-field results
still receive a one-element tuple and run final contract validation.

Multi-field RETURNING retains general ordered iteration and no longer needs its
per-row scalar-unwrapping condition. Whole-model RETURNING and SELECT are
unchanged. Backend/validation/extension policies, empty results, SQL, cardinality,
transaction ownership, driver/error boundaries and checkpoints are unchanged.
No new cache, persistent field, public API, dependency or driver change.

## Wide buffered SQLite UPDATE RETURNING

Private disk-backed SQLite with 2,000 `(id, units, amount) = (n, 2*n, n/2)` rows.
Prebuilt queries/shared transaction. UPDATE sets `units = units + 0` and selects
rows through a key predicate; RETURNING has no explicit ordering. The SELECT
control orders by key. Each operation consumes all results and checks count and
endpoint values for this fixture/backend. Six alternating B/C processes, six
trials × 100 operations after ten warmups: **18 samples/workload/revision**.

| Workload, 1,000 rows/operation | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| Three-field named SELECT control | 318.49 | 300.38 | 0.943× |
| Three-field tuple RETURNING control | 480.90 | 468.90 | 0.975× |
| Single integer scalar RETURNING | 869.99 | 1,212.79 | **1.394×** |
| Single integer named RETURNING | 469.38 | 554.45 | **1.181×** |

Target gains align with removed iteration; adverse controls are retained, not
normalized away. **This is not durable-commit-per-operation performance** and
does not establish gains for INSERT/DELETE, MariaDB, arbitrary field types or
streaming. Cross-shape throughput reflects different contracts and is not an
optimization gain. The SELECT control's ~5.7% decline remains part of the result.

## One-row results and longer controls

Primary one-row trials: six × 2,000 operations after 200 warmups per process.

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Three-field named SELECT | 10,754 | 9,001 |
| Three-field tuple RETURNING | 8,713 | 8,357 |
| Single scalar RETURNING | 9,571 | 9,594 |
| Single named RETURNING | 10,028 | 8,227 |

The primary named-write decline is **~18%**, not hidden by its wide-row gain.
Longer named-read controls were scheduled before primary results: six processes,
ten × 5,000 reads after 1,000 warmups, rotating adapters, **30 samples per adapter
and revision**. Forward B/C and reverse C/B are separate unpinned series; pinned
C/B uses CPU 2. Raw executes the same compiled SELECT and strictly validates its
named result, not the entire runtime contract.

| Named-read series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Unpinned B/C | snekql | 9,839 | 9,230 |
| Unpinned B/C | raw | 26,829 | 24,865 |
| Unpinned C/B | snekql | 9,114 | 9,539 |
| Unpinned C/B | raw | 27,882 | 27,368 |
| Pinned C/B | snekql | 11,978 | 11,981 |
| Pinned C/B | raw | 33,694 | 34,038 |

Pinned named-read main-thread CPU µs/read: **76.306 → 76.274**; raw
**19.793 → 19.442**. Reversed results differ; affinity does not establish why
primary or longer unpinned controls moved. No read-path speedup claim.

### Dedicated named-write and tuple-write repeats

Scheduled after observing primary declines: same longer protocol, rotating
shape/adapter order, unpinned B/C and then separately pinned C/B. Raw and snekql
use **separate identically seeded files** to avoid competing write locks; each
holds its own transaction. Raw consumes the same compiled SQL, validates the
single named model, and retains the native three-field tuple for its control.
It does not implement the whole runtime/codec contract.

| Write repeat | Workload | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | --- | ---: | ---: |
| Unpinned B/C | Named single | snekql | 8,697 | 8,835 |
| Unpinned B/C | Named single | raw | 24,768 | 25,075 |
| Unpinned B/C | Three-field tuple | snekql | 8,699 | 8,523 |
| Unpinned B/C | Three-field tuple | raw | 25,940 | 25,862 |
| Pinned C/B | Named single | snekql | 10,496 | 10,541 |
| Pinned C/B | Named single | raw | 32,049 | 31,673 |
| Pinned C/B | Three-field tuple | snekql | 10,065 | 9,993 |
| Pinned C/B | Three-field tuple | raw | 32,896 | 32,469 |

Named target CPU µs/operation: unpinned **99.854 → 98.716**, pinned
**79.081 → 78.568**. Tuple control: unpinned **100.484 → 102.796**, pinned
**82.732 → 83.229**. The initial large named decline was not repeated, but is not
causally explained. Tuple writes still declined (~2% unpinned/~0.7% pinned).
No isolated general one-row write gain or blanket non-regression claim.

Independent comparative point reads build queries/use per-read transactions with
the standard fixture after each primary database closes: six rotating adapter
trials × 2,000 reads after 200 warmups.

| Comparative adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 11,720 | 10,924 |
| snekql | 2,861 | 2,723 |
| SQLAlchemy | 2,695 | 2,627 |

Do not pool different series, normalize using raw, or multiply historical gains.
Host was not exclusively controlled; moving controls limit causal attribution.

## Retention and allocation

Separate tracemalloc probes retain 20 operations × 1,000 rows, three trials per
shape/revision. These are traced result/peak allocations, not RSS/native buffers
or isolated setup latency. The existing decoder tuple is still built per batch;
a local decoder reference and one-field branch do not add persistent storage.
Named results still require their one-element values tuple and final model.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Three-field named SELECT | 10,894,441 → 10,894,441 | 10,970,321 → 10,970,321 |
| Three-field tuple RETURNING | 2,410,464 → 2,410,464 | 2,498,200 → 2,498,200 |
| Single scalar RETURNING | 178,107 → 178,107 | 253,288 → 253,136 |
| Single named RETURNING | 10,098,174 → 10,098,174 | 10,166,606 → 10,166,606 |

Retention unchanged; peaks flat/slightly lower. Different result contracts have
different allocation needs, including native small-integer sharing. Low scalar
retention is not a before/after gain or a general arbitrary-value estimate.

## Diagnostic profiles

Separate profiles, 100 operations × 1,000 rows per shape:

| Call count | Baseline → Candidate |
| --- | ---: |
| Scalar RETURNING decode-generator resumptions | **200,000 → 0** |
| Named single RETURNING decode-generator resumptions | **200,000 → 0** |
| Scalar column decodes | 100,000 → 100,000 |
| Named single column decodes | 100,000 → 100,000 |
| Named single final materializations | 100,000 → 100,000 |
| Either three-field control's generator resumptions | 400,000 → 400,000 |
| Either three-field control's column decodes | 300,000 → 300,000 |

Counts include generator exhaustion. No codec/final validation bypass;
profile timing is diagnostic, not throughput evidence.

## Validation and provenance

Six new public transaction cases pass baseline/candidate:

- SQLite/MariaDB INSERT and bulk results preserve collection-valued scalars,
  named models/final transformation, empty scalar/named batches.
- SQLite/MariaDB bulk RETURNING preserves text-storage versus logical integer
  behavior across False/True/False validation reuse, nullable named fields and
  exactly-once named transformations.
- SQLite UPDATE retains custom projection-policy precedence and validation reuse
  for scalar/named fields. Named validation failures on UPDATE/DELETE leave the
  already-written/deleted state observable through public reads, with usable
  transactions; subsequent scalar deletes and empty named results remain correct.

Unsafe mutations caught/restored: decoder bypass **6 failures**, named-contract
bypass **2 failures/4 errors**, scalar tuple-wrapping **6 failures**.
**51 focused passed**, covering existing projection/named codecs and whole-model
RETURNING/SELECT behavior. Full suite **4,079 passed**, exit 0, **953.06s**.
Ruff/format/ty/whitespace pass; CI status is tracked in the PR. Tests assert public
behavior, not speed/private call counts.

Owned tests, timings, profiles and memory ran sequentially on clean measured
revisions. No failed/cancelled benchmark samples discarded. Published **1,260
samples**: 288 primary, 120 forward, 120 reverse, 120 pinned, 240 write-unpinned,
240 write-pinned, 24 memory, 108 comparative.

- [Probe commands/metadata](results/single-returning-526/probe-manifest.json)
- [Primary timing](results/single-returning-526/timing-trials.csv)
- [Forward reads](results/single-returning-526/forward-trials.csv)
- [Reverse reads](results/single-returning-526/reverse-trials.csv)
- [Pinned reads](results/single-returning-526/pinned-trials.csv)
- [Unpinned writes](results/single-returning-526/target-unpinned-trials.csv)
- [Pinned writes](results/single-returning-526/target-pinned-trials.csv)
- [Memory](results/single-returning-526/memory-trials.csv)
- [Comparative trials](results/single-returning-526/comparative-trials.csv)
- [Comparative provenance](results/single-returning-526/comparative-manifest.json)

Raw evidence `/home/crpier/.cache/snekql-526/`; discovery/tests/mutations
`/home/crpier/.cache/snekql-single-returning-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F/28 logical CPUs, powersave. Private Btrfs databases,
SQLite WAL/NORMAL. Only labeled series pin CPU 2; no exclusive host control.

## Reproduction

Identical dependencies, exact clean revisions, `PYTHON_CONTEXT_AWARE_WARNINGS=1`,
private disk-backed `TMPDIR`, scripts outside worktrees. Save JSON per fresh
process. Primary B/C alternation three times; memory/profiles separately. After
each primary timing process:

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
    if shape in ("scalar-returning", "single-returning", "tuple-returning"):
        q = (
            sqlite.update(Metric)
            .set(Metric.units.to_expr(Metric.units.add(0)))
            .where(Metric.id.lte(width))
        )
        if shape == "scalar-returning":
            return q.returning(Metric.id)
        if shape == "single-returning":
            return q.returning_as(Single, value=Metric.id)
        return q.returning(Metric.id, Metric.units, Metric.amount)
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
                    "named-read",
                    "tuple-returning",
                    "scalar-returning",
                    "single-returning",
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
                            if shape == "scalar-returning":
                                return row
                            if shape == "single-returning":
                                return row.value
                            if shape == "tuple-returning":
                                return row
                            return (
                                row.key if shape == "named-read" else row.id,
                                row.units,
                                row.amount,
                            )

                        assert values(rows[0]) == (
                            1
                            if shape in ("scalar-returning", "single-returning")
                            else (1, 2, 0.5)
                        )
                        assert values(rows[-1]) == (
                            width
                            if shape in ("scalar-returning", "single-returning")
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

### Read controls: `python followup.py PHASE_INDEX`

Keep beside `probe.py`; phases 0–5, B/C then separately C/B.

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

### Pinned read control: `taskset -c 2 python pinned.py PHASE_INDEX`

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

### Write repeats: `python target.py PHASE_INDEX`

Phases 0–5, B/C unpinned; separately C/B with `taskset -c 2`.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from probe import Single, seed, query, sqlite


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snekql.db"
        raw_path = Path(directory) / "raw.db"
        await seed(path, 2000)
        await seed(raw_path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
            connect(raw_path, isolation_level=None) as raw,
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

            async def prepare(shape):
                q = query(1, shape)
                compiled = q.compile()

                def check(row):
                    if shape == "single-returning":
                        assert row.value == 1
                    else:
                        assert row == (1, 2, 0.5)

                async def snekql_write():
                    rows = await tx.execute(q)
                    assert len(rows) == 1
                    check(rows[0])

                async def raw_write():
                    async with raw.execute(compiled.sql, compiled.params) as cursor:
                        rows = await cursor.fetchall()
                    assert len(rows) == 1
                    row = (
                        Single.model_validate(
                            {"value": rows[0][0]},
                            strict=True,
                            by_alias=False,
                            by_name=True,
                        )
                        if shape == "single-returning"
                        else rows[0]
                    )
                    check(row)

                return [(shape, "snekql", snekql_write), (shape, "raw", raw_write)]

            operations = [
                *(await prepare("single-returning")),
                *(await prepare("tuple-returning")),
            ]
            for _, _, op in operations:
                for _ in range(1000):
                    await op()
            for trial in range(10):
                shift = (trial + int(sys.argv[1])) % len(operations)
                for shape, adapter, op in operations[shift:] + operations[:shift]:
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
