# Execution-local ordinary SUM normalization — #508

Measured 2026-10-23 (UTC): merged baseline `875f479` (including #507) versus clean
implementation `c213e4e`. Incremental comparison, not multiplied previous gains.

## Change and scope

SUM repeated its numeric-policy protocol check and source resolution for each
result value. Exact built-in SUM nodes over Attr columns without a complete
`NumericAggregatePolicy` now resolve ordinary normalization once per execution.
Integer storage still produces int, Real still produces float, other storage
kinds retain the existing pass-through, and SQL NULL bypasses normalization.

SUM still does **not** adopt ordinary column validation or projection codecs.
Complete numeric policies and derived/unknown sources retain general dispatch;
incomplete numeric hooks are not mistaken for the protocol. MIN/MAX retain their
distinct policy rules in the aggregate-resolution helper. AVG/COUNT are unchanged.
No global/query cache, SQL rewrite, dependency, driver, API or checkpoint change.

## Targeted wide results

Private disk-backed SQLite. A numeric model has `id: int`, `units: int`, and
`amount: float`; 2,000 rows hold `(n, 2*n, n/2)` for n=1..2000. This is a different
fixture from earlier reports: comparisons are **within each revision pair**, not
across reports. Grouped workloads return 1,000 singleton groups, deliberately
exposing result-decoding cost. Larger groups or SQL-heavy queries may differ.

Prebuilt queries, shared transactions, three optional named result fields, ordered
results; every read checks count and endpoint values. Six fresh B/C/B/C/B/C
processes, six 100-operation trials after ten warmups per workload/process:
**18 samples per workload/revision**.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control | 323.41 | 327.04 | 1.011× |
| Three MIN/MAX fields, control | 309.31 | 308.88 | 0.999× |
| One SUM plus two extrema | 163.85 | 334.37 | **2.041×** |
| Three SUM fields | 95.58 | 445.12 | **4.657×** |

These numeric SUM reads improve substantially with approximately flat wide
controls. SUM's numeric normalization is cheaper than ordinary logical column
validation **by its existing semantics**, not because this change skips required
validation. No universal, MariaDB, streaming or tail-latency gain is inferred.

## Single-row results and controls

Primary one-row runs use six 2,000-operation trials after 200 warmups:

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 9,498 | 10,293 |
| MIN/MAX control | 8,380 | 7,633 |
| One SUM plus two extrema | 8,977 | 8,963 |
| Three SUM fields | 8,476 | 9,218 |

Before observing these results, longer ordinary-read controls were scheduled in
both revision orders. Each series has six processes, ten 5,000-operation trials
after 1,000 warmups per adapter/process, alternating adapter order per trial and
initial order by process: **30 samples per adapter/revision/series**. Raw executes
the same compiled SQL/bindings and strict named-result validation, but not the full
snekql runtime contract. Transactions are shared and queries prebuilt.

| Unpinned ordinary-read series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| B/C/B/C/B/C | snekql | 10,914 | 10,665 |
| B/C/B/C/B/C | raw | 31,234 | 29,426 |
| C/B/C/B/C/B | snekql | 10,848 | 10,038 |
| C/B/C/B/C/B | raw | 29,280 | 28,802 |

The primary ordinary-read increase did not persist. The reversed series decreases
more than raw, and the primary extrema control also decreases. Those results were
investigated rather than discarded.

A further C/B/C/B/C/B series pins the process and inherited threads to logical CPU
2 (`taskset -c 2`). Each process warms both ordinary and extrema workloads, then
rotates all four workload/adapter combinations per trial. Same 1,000 warmups,
ten 5,000-operation trials: **30 samples per workload/adapter/revision**.

| Pinned series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| Ordinary projection | snekql | 12,204 | 12,182 |
| Ordinary projection | raw | 34,368 | 34,720 |
| Three extrema | snekql | 9,818 | 9,729 |
| Three extrema | raw | 34,134 | 34,385 |

Pinned snekql main-thread CPU: ordinary **74.939 → 75.000 µs/read**, extrema
**94.159 → 95.007 µs/read**. The ordinary result is approximately flat; extrema
remain about 0.9% slower in this repeat, consistent with a small setup cost but
not an isolated causal measurement of it. The new helper adds per-execution
aggregate dispatch; all such setup is included in timings.

Pinning changes execution conditions and does not grant exclusive host control.
These results do **not** fully explain all unpinned variation or prove every query
unaffected. All series remain separate and published. **No general point-read
gain or blanket absence-of-regression claim is made.**

Independent comparative processes follow each primary timing process after its
database closes: ordinary point reads, per-operation query construction and
per-read transactions, six rotating adapter trials of 2,000 operations after 200
warmups. These use the standard comparative fixture, not the numeric model above.

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,904 | 14,102 |
| snekql | 3,165 | 3,238 |
| SQLAlchemy | 3,251 | 3,255 |

Results are not normalized by moving control ratios.

## Separate memory and profiles

Tracemalloc retains 20 reads × 1,000 result rows, three samples/workload/revision:

| Workload | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary projection | 10,894,441 → 10,894,441 | 10,970,305 → 10,970,305 |
| Three extrema | 10,894,470 → 10,894,470 | 10,971,630 → 10,971,630 |
| One SUM | 10,894,470 → 10,894,470 | 10,972,158 → 10,971,502 |
| Three SUMs | 10,894,470 → 10,894,470 | 10,971,310 → 10,971,246 |

Output retention is unchanged; traced peaks are approximately unchanged. This is
not total RSS or isolated setup allocation. Normalization partials/NULL closures
are execution-local, not persistent query/output-row state.

Separate profiles consume 100 × 1,000 result rows:

| Diagnostic count | One SUM, B → C | Three SUMs, B → C |
| --- | ---: | ---: |
| Structural protocol checks | 101,000 → 1,100 | 301,000 → 1,300 |
| Static lookups | 100,900 → 1,000 | 300,900 → 1,200 |
| `_normalize_sum` | 100,000 → 100,000 | 300,000 → 300,000 |
| Column decodes for the two extrema | 200,000 → 200,000 | Not applicable |
| Final named-result materializations | 100,000 → 100,000 | 100,000 → 100,000 |

SUM did not call ordinary Attr.decode before this change and still does not.
Counts support avoided dispatch and retained required work. Profile durations are
not the throughput estimates.

## Validation and evidence

Ten new public cases pass on baseline/candidate: buffered/streamed reads, complete
and incomplete numeric hooks, projection-policy independence, empty inputs and
query reuse. SQLite/MariaDB tests verify Integer/Real result types and confirm that
SUM does not apply ordinary column logical constraints, even with validation on.
Unsafe numeric-policy bypass, missing NULL handling, adoption of column validation
and lost integer normalization are caught and reverted.

Focused aggregate/scalar/compiler coverage: **83 passed**. Full local suite:
**4,005 passed**, exit 0, 879.56s. Static/CI status is recorded in the PR. No
private-call-count or speed assertions enter CI.

Published **900 samples**:

- [288 primary timings](results/sum-decoders-508/timing-trials.csv),
  [120 forward controls](results/sum-decoders-508/forward-trials.csv),
  [120 reverse controls](results/sum-decoders-508/reverse-trials.csv),
  [240 pinned controls](results/sum-decoders-508/pinned-trials.csv),
  [24 memory samples](results/sum-decoders-508/memory-trials.csv), and
  [probe provenance/commands](results/sum-decoders-508/probe-manifest.json).
- [108 comparative trials](results/sum-decoders-508/comparative-trials.csv) and
  [environment/session/command metadata](results/sum-decoders-508/comparative-manifest.json).

A correctness-only preflight passed all four numeric workloads. Full validation
finished before timings. Owned timing, memory, profiles and follow-ups ran
sequentially; all retained measurement commands exited zero with clean source
trees. Raw reports/profiles remain in `/home/crpier/.cache/snekql-508/`; discovery
and mutation evidence is in `/home/crpier/.cache/snekql-sum-next/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Primary/forward/reverse runs
are unpinned; only the labeled series uses CPU 2. No exclusive host control.
Private Btrfs databases, SQLite WAL/NORMAL. Visible-test checks before commands do
not prevent other sessions starting work during measurements.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1` and private disk-backed
`TMPDIR`. Save scripts outside source roots; run from the exact worktrees above.
Primary timing: six B/C alternating processes. Memory/profiles run separately.
The independent comparative command after each primary timing process is:

```bash
python -m benchmarks.compare --backend sqlite --workload point-read \
    --rows 2000 --operations 2000 --trials 6 --warmup 200
```

### Primary: `python probe.py timing`, `memory`, or `profile`

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


def query(width, shape):
    q = sqlite.select(Metric).where(Metric.id.lte(width))
    if shape == "plain":
        return q.project(
            Record, key=Metric.id, units=Metric.units, amount=Metric.amount
        ).order_by(Metric.id.asc())
    if shape == "extrema":
        fields = (Metric.id.min(), Metric.units.max(), Metric.amount.min())
    elif shape == "one":
        fields = (Metric.id.sum(), Metric.units.min(), Metric.amount.max())
    else:
        fields = (Metric.id.sum(), Metric.units.sum(), Metric.amount.sum())
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
                for shape in ("plain", "extrema", "one", "three"):
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

### Unpinned controls: `python followup.py PHASE_INDEX`

Use phases 0–5, first B/C alternating, then C/B alternating. Keep this script
beside `probe.py`, which supplies the identical fixture and query.

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

Use C/B alternating phases 0–5; this script also imports `probe.py`.

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
