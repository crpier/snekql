# Guarded native multi-field decoder iteration — #532

Measured 2026-10-24 UTC, clean baseline **`fa8f670`** (merged #531) versus
candidate **`adbac50`**. Explicit multi-field SELECT and RETURNING retain all
column decodes and final named contracts while replacing a per-row generator
with strict native `map` iteration. Single-field, whole-model and whole-source
CTE/join materializers are unchanged; no cache/dependency/public interface change.

## Contract and implementation

The former expression was `tuple(decode(value) for decode, value in
zip(decoders, row, strict=True))`. Each three-field row resumes a generator four
times, including its exhaustion. The candidate uses
`tuple(map(_decode_field, decoders, row, strict=True))` in the explicit SELECT
and multi-field RETURNING paths. Existing row-width assertions remain.

**A bare `map(operator.call, ...)` is unsafe.** A custom decoder may raise
`StopIteration`. The existing generator converts that to
`RuntimeError("generator raised StopIteration")`, with the original exception
as its cause. Native iteration would instead truncate the tuple silently.
The small `_decode_field` helper preserves that failure and ordered effects;
it is called for every field, including built-ins. Other failures propagate.
There is no direct `pydantic_core` shortcut, skipped codec, assumed output type,
unrolled fixed arity, persistent decoder cache or weakened final validation.

## Protocol and scope

Private disk-backed SQLite, preseeded 2,000-row fixture
`(id, units, amount) = (n, 2*n, n/2)`. Prebuilt queries, open shared transaction;
SELECTs are buffered. UPDATE RETURNING writes `units = units + 0`, so this is
**not** durable-commit-per-write latency, nor INSERT/DELETE/MariaDB throughput
evidence. Every operation checks count and first/last logical values.

Six alternating fresh processes, B/C × 3, then separate C/B × 3, then separate
C/B × 3 pinned to CPU 2. Each process has six timed trials per shape/width:

- Wide: 100 operations/trial, ten warmups, 1,000 rows/operation.
- One row: 2,000 operations/trial, 200 warmups.
- **18 samples/shape/revision/series**, reported as medians of ops/s.

Named SELECT is `plain` in raw files; tuple SELECT is `tuple`. `model` and
`scalar` are unchanged whole-model/single-field controls. `tuple-returning` and
`named-returning` are explicit three-field UPDATE projections.

## Wide buffered SQLite results

| Series | Shape | Baseline | Candidate | Ratio |
| --- | --- | ---: | ---: | ---: |
| Initial B/C | Named SELECT | 324.84 | 341.21 | 1.050× |
| Initial B/C | Tuple SELECT | 526.31 | 580.55 | 1.103× |
| Initial B/C | Tuple RETURNING | 494.54 | 539.45 | 1.091× |
| Initial B/C | Named RETURNING | 324.44 | 341.36 | 1.052× |
| Initial B/C | Model SELECT control | 347.23 | 354.37 | 1.021× |
| Initial B/C | Scalar SELECT control | 1475.01 | 1479.38 | 1.003× |
| Reverse C/B | Named SELECT | 308.02 | 309.57 | 1.005× |
| Reverse C/B | Tuple SELECT | 494.52 | 519.38 | 1.050× |
| Reverse C/B | Tuple RETURNING | 472.53 | 499.71 | 1.058× |
| Reverse C/B | Named RETURNING | 293.91 | 320.25 | 1.090× |
| Reverse C/B | Model SELECT control | 325.55 | 335.44 | 1.030× |
| Reverse C/B | Scalar SELECT control | 1359.14 | 1379.40 | 1.015× |
| Pinned C/B | Named SELECT | 325.78 | 350.68 | 1.076× |
| Pinned C/B | Tuple SELECT | 531.94 | 579.32 | 1.089× |
| Pinned C/B | Tuple RETURNING | 502.73 | 523.66 | 1.042× |
| Pinned C/B | Named RETURNING | 323.94 | 334.98 | 1.034× |
| Pinned C/B | Model SELECT control | 351.70 | 353.76 | 1.006× |
| Pinned C/B | Scalar SELECT control | 1449.93 | 1483.47 | 1.023× |

Tuple SELECT improves ~5–10%; tuple RETURNING ~4–9% in these series. Named
results show smaller/more variable gains (~0.5–7.6% SELECT, ~3.4–9% RETURNING).
Controls also move. No raw normalization, pooled-series confidence interval,
broad backend gain, or attribution of every difference to the candidate.

## One-row results: mixed, not a blanket improvement

| Series | Shape | Baseline | Candidate |
| --- | --- | ---: | ---: |
| Initial B/C | Named SELECT | 10,567 | 9,763 |
| Initial B/C | Tuple SELECT | 10,980 | 10,202 |
| Initial B/C | Tuple RETURNING | 10,109 | 10,131 |
| Initial B/C | Named RETURNING | 9,540 | 9,629 |
| Initial B/C | Model control | 11,711 | 12,701 |
| Initial B/C | Scalar control | 12,850 | 14,267 |
| Reverse C/B | Named SELECT | 10,074 | 9,026 |
| Reverse C/B | Tuple SELECT | 8,475 | 9,797 |
| Reverse C/B | Tuple RETURNING | 8,896 | 7,857 |
| Reverse C/B | Named RETURNING | 7,819 | 7,676 |
| Reverse C/B | Model control | 10,318 | 9,250 |
| Reverse C/B | Scalar control | 12,731 | 11,991 |
| Pinned C/B | Named SELECT | 11,701 | 11,945 |
| Pinned C/B | Tuple SELECT | 12,178 | 12,501 |
| Pinned C/B | Tuple RETURNING | 9,975 | 9,840 |
| Pinned C/B | Named RETURNING | 9,477 | 9,574 |
| Pinned C/B | Model control | 12,616 | 12,646 |
| Pinned C/B | Scalar control | 14,449 | 14,290 |

Adverse named SELECT results (~8% initial, ~10% reverse) and reverse tuple
RETURNING (~12%) remain. Pinned tuple RETURNING still declines ~1.4%, while
pinned tuple SELECT improves ~2.7%. Do not turn these into a non-regression
claim or explain them away with host scheduling.

### Longer named SELECT follow-ups

Separate six-process series, ten trials × 5,000 operations after 1,000 warmups;
snekql/raw adapter order alternates per trial. Same prepared named query. Raw
uses `execute/fetchall/close` and the same strict Pydantic final contract but not
snekql column decoding, so it is a moving control, **not a normalization factor**.
CPU is main-thread `thread_time`, not total CPU/worker time.

| Series | Adapter | Ops/s B → C | Main-thread µs/op B → C |
| --- | --- | ---: | ---: |
| B/C | snekql | 10,078.69 → 10,133.21 | 92.767 → 92.336 |
| B/C | Raw | 27,704.14 → 26,930.34 | 25.748 → 26.687 |
| C/B | snekql | 8,617.80 → 8,319.96 | 108.193 → 112.083 |
| C/B | Raw | 25,850.35 → 23,222.76 | 27.469 → 31.209 |
| CPU 2 C/B | snekql | 11,349.13 → 11,906.25 | 80.439 → 76.627 |
| CPU 2 C/B | Raw | 32,468.85 → 33,761.68 | 20.471 → 19.677 |

The longer reversed named query also declines (~3.5%); pinned improves (~4.9%).
The large primary declines were not repeated at their original magnitude,
but remain unexplained. Affinity is a labeled additional measurement, not
proof of the cause of unpinned movement.

### Longer one-row UPDATE RETURNING follow-ups

Same ten × 5,000 protocol, rotating named/tuple and raw/snekql order. Separate,
identically seeded database files/open transactions for raw and snekql avoid
competing write locks. These are shared-transaction no-op UPDATEs, not durable
commit latency. Named raw results use the same strict Pydantic contract.

| Series | Shape / adapter | Ops/s B → C | Main-thread µs/op B → C |
| --- | --- | ---: | ---: |
| B/C | Named / snekql | 9,223.25 → 9,148.90 | 95.758 → 96.109 |
| B/C | Named / raw | 27,242.55 → 28,032.17 | 24.899 → 23.955 |
| B/C | Tuple / snekql | 9,653.95 → 9,578.17 | 90.831 → 91.321 |
| B/C | Tuple / raw | 28,719.80 → 29,157.54 | 22.933 → 22.523 |
| CPU 2 C/B | Named / snekql | 9,278.10 → 9,447.73 | 90.142 → 88.474 |
| CPU 2 C/B | Named / raw | 29,330.08 → 30,211.57 | 21.637 → 20.871 |
| CPU 2 C/B | Tuple / snekql | 9,655.62 → 9,990.91 | 86.211 → 83.281 |
| CPU 2 C/B | Tuple / raw | 31,564.21 → 32,306.99 | 19.683 → 19.074 |

Unpinned writes still decline ~0.8% while raw improves. Pinned writes improve;
this does not establish a general one-row win or eliminate the adverse results.

### Comparative harness, fresh query per operation

Six B/C processes, repository `benchmarks.compare`, SQLite point-read, 2,000
rows/operations, six trials after 200 warmups. Eighteen trials/adapter/revision:

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Raw | 13,800.12 | 12,720.17 |
| snekql | 3,237.58 | 3,215.61 |
| SQLAlchemy | 2,899.70 | 3,060.19 |

No comparative point-throughput improvement established. This includes query
construction unlike the prepared-query probes; results are not interchangeable.

## Output memory and setup cost

Separate tracemalloc runs retain 20 × 1,000 results, three trials per shape and
revision. Retention below is unchanged; peak differences are tiny.

| Shape | Retained bytes, both | Peak bytes B → C |
| --- | ---: | ---: |
| Named SELECT | 10,894,441 | 10,970,321 → 10,970,321 |
| Tuple SELECT | 2,413,689 | 2,424,707 → 2,424,643 |
| Tuple RETURNING | 2,410,464 | 2,498,200 → 2,497,832 |
| Named RETURNING | 10,890,529 | 10,975,673 → 10,975,673 |
| Model control | 4,494,409 | 4,571,945 → 4,571,945 |
| Scalar control | 186,790 | 252,661 → 252,661 |

Not RSS/native driver buffers/import overhead. There is one new module-level
helper function, no persistent per-query/per-model/per-descriptor cache or new
plan field. Each multi-field value now pays a helper call to preserve
StopIteration semantics; an ephemeral map replaces the ephemeral generator/zip.
Import/startup cost was not isolated or claimed as a gain. Query construction
and decoder setup are unchanged in source, not proven performance-free.

## Profile accounting, not a speed benchmark

Separate profiles perform 100 × 1,000-row operations per shape/revision:

| Each three-field target | Baseline → Candidate |
| --- | ---: |
| Projection generator resumptions | **400,000 → 0** |
| Guard helper calls | **0 → 300,000** |
| Column decodes | **300,000 → 300,000** |
| Pydantic adapter validations | **300,000 → 300,000** |
| Named final materializations, named shapes | **100,000 → 100,000** |

Do not call this “300,000 fewer decoder calls”; native iteration still invokes
every decoder and adds a guard call. Scalar control retains 100,000 decodes,
model control 300,000. The profile cannot substitute for unprofiled timing.

## Public-behavior validation

`tests/runtime/test_multi_field_decoding.py`: **13 cases pass baseline and
candidate** through public runtime/descriptor extension seams, without speed or
private-call-count assertions:

- Ordered, exactly-once custom policy effects with False/True/False query reuse;
  tuple/named SELECT via buffered, chunked and `fetch_one`, plus UPDATE RETURNING.
- A second decoder raises StopIteration: original RuntimeError/cause retained,
  no third decoder effect, no silently truncated result, transaction remains usable.
- Named contract validation still occurs after decoding; materialization failure
  does not roll back an already-executed UPDATE or poison its transaction.
- SQLite/MariaDB UUID plus JSON collection codecs, two-field positional reversal
  and final named shape, buffered/chunked/one and bulk INSERT RETURNING.

Unsafe mutations (all restored):

- Unguarded StopIteration: **4 failures / 1 pass** at the initial five-case slice.
- Bypass decoding: **5 failures / 0 pass** at that slice.
- Reverse RETURNING decoder order: **2 failures / 3 passes** at that slice.
- Bypass multi-field named contracts: **13 failures / 0 pass** on final cases.

**57 focused passed** after restoration, **4,098 full tests passed in 1,232.14s**;
Ruff/format/ty/whitespace checks pass. Full suite used private disk-backed
TMPDIR and `PYTHON_CONTEXT_AWARE_WARNINGS=1`; background runner restored the
default Python SIGINT handler. Tests, timing, profiles and memory ran sequentially.
Test-authoring preflights corrected a missing UPDATE `all()` safety opt-in,
unsupported `assert_raises(match=...)`, Ruff async-comprehension/import formatting.
These were not timed samples or suppressed suite failures.

## Decision and limitations

Propose this small, semantics-guarded implementation for **multi-row explicit
projections**, supported by repeated tuple and named RETURNING gains. Named
SELECT gains are variable; point results are mixed and adverse results remain.
No claim for streaming throughput, other backends, whole-source joins/CTEs,
all arities, raw validation-off performance, durable commits or exclusive-host
causality. The existing public tests cover semantics on both backends, not
cross-backend performance. No multiplication with historical performance gains.

## Evidence and reproduction

**2,280 published sample records:** 432 primary, 432 reverse-wide, 432 pinned-wide,
360 longer reads, 480 longer writes, 36 memory, 108 comparative. Profiles separate.
All measured revision metadata reports clean trees. Raw evidence:
`/home/crpier/.cache/snekql-532/`; test/mutation/discovery logs:
`/home/crpier/.cache/snekql-codec-next/`. No failed/cancelled measurement run.

- [Probe manifest](results/multi-field-532/probe-manifest.json)
- [Primary](results/multi-field-532/timing-trials.csv),
  [reverse-wide](results/multi-field-532/reverse-wide-trials.csv),
  [pinned-wide](results/multi-field-532/pinned-wide-trials.csv)
- [Longer reads B/C](results/multi-field-532/forward-trials.csv),
  [C/B](results/multi-field-532/reverse-trials.csv),
  [pinned](results/multi-field-532/pinned-trials.csv)
- [Longer writes B/C](results/multi-field-532/write-forward-trials.csv),
  [pinned C/B](results/multi-field-532/write-pinned-trials.csv)
- [Memory](results/multi-field-532/memory-trials.csv)
- [Comparative trials](results/multi-field-532/comparative-trials.csv),
  [comparative manifest](results/multi-field-532/comparative-manifest.json)

CPython 3.15.0, SQLite 3.53.1, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, SQLAlchemy 2.1.1; i7-14700F/28 logical CPUs, powersave,
private Btrfs SQLite WAL/NORMAL. Shared host, no exclusive control. Only labeled
pinned series use CPU 2. Other application/development activity not controlled.

Use clean baseline/candidate worktrees with identical dependencies. Save scripts
below together **outside** worktrees; set a private disk-backed TMPDIR and
`PYTHON_CONTEXT_AWARE_WARNINGS=1`. Use the same interpreter for both worktrees.
Run each mode sequentially, keeping stdout JSON and stderr separately:

- `python probe.py timing`: six fresh B/C processes, then separate C/B × 3,
  then C/B × 3 under `taskset -c 2`.
- `python probe.py memory` and `profile`: once per revision, separately.
- `python followup.py INDEX`: six B/C, six C/B, six pinned C/B; INDEX 0–5.
- `python target.py INDEX`: six B/C then six pinned C/B; INDEX 0–5.
- Comparative: six B/C processes running
  `python -m benchmarks.compare --backend sqlite --workload point-read
  --rows 2000 --operations 2000 --trials 6 --warmup 200`.

### `probe.py`

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
    if shape.endswith("returning"):
        q = (
            sqlite.update(Metric)
            .set(Metric.units.to_expr(Metric.units.add(0)))
            .where(Metric.id.lte(width))
        )
        return (
            q.returning_as(
                Record, key=Metric.id, units=Metric.units, amount=Metric.amount
            )
            if shape == "named-returning"
            else q.returning(Metric.id, Metric.units, Metric.amount)
        )
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
    return (
        q
        if shape == "model"
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
                    "plain",
                    "tuple",
                    "tuple-returning",
                    "named-returning",
                    "model",
                    "scalar",
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
                            if shape == "scalar":
                                return row
                            if shape in ("tuple", "tuple-returning"):
                                return row
                            return (
                                row.id if shape == "model" else row.key,
                                row.units,
                                row.amount,
                            )

                        assert values(rows[0]) == (
                            1 if shape == "scalar" else (1, 2, 0.5)
                        )
                        assert values(rows[-1]) == (
                            width
                            if shape == "scalar"
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

### `followup.py`

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

### `target.py`

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from probe import Record, seed, query, sqlite


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
                    if shape == "named-returning":
                        assert (row.key, row.units, row.amount) == (1, 2, 0.5)
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
                        Record.model_validate(
                            dict(zip(("key", "units", "amount"), rows[0], strict=True)),
                            strict=True,
                            by_alias=False,
                            by_name=True,
                        )
                        if shape == "named-returning"
                        else rows[0]
                    )
                    check(row)

                return [(shape, "snekql", snekql_write), (shape, "raw", raw_write)]

            operations = [
                *(await prepare("named-returning")),
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
