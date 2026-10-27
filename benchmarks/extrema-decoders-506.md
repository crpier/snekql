# Execution-local ordinary MIN/MAX decoding — #506

Measured 2026-10-23 (UTC): merged baseline `787a498` (including #505) versus clean
implementation `bb2e956`. Incremental comparison, not multiplied previous gains.

## Change and scope

Grouped extrema repeatedly checked their source's policy protocol and resolved
its column decoder for each result value. Exact built-in MIN/MAX nodes over Attr
columns without policy extensions now resolve their decoder once per execution.
SQL NULL still bypasses the source codec, even for a NOT NULL column.

Extrema retain their own semantics: **dialect-only projection hooks do not become
MIN/MAX codecs**. Policy-extended and non-column/derived aggregate sources retain
general dispatch. SUM, AVG and COUNT retain their previous normalization and empty
result behavior. Normal `Attr.decode` and per-execution validation still run.

Built-in expression setup is isolated in a helper after the ordinary-column fast
path, keeping the main resolver's complexity bounded. Scalar handling is moved
there without changing its behavior. There is no global/query cache, dependency,
SQL rewrite, driver, public API or runtime/checkpoint change.

## Targeted wide results

Private disk-backed SQLite, 2,000 seeded rows. Each grouped probe returns 1,000
**singleton groups** (one source row per group), deliberately exposing decoding
cost. Larger input groups or SQL-heavy aggregation may have a different gain.
Prebuilt queries/shared transactions, three named result fields, ordered results;
each operation checks count and endpoint values.

Six fresh alternating processes B/C/B/C/B/C; six 100-operation trials after ten
warmups per case/process: **18 samples per case/revision**.

| Workload | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control, no grouping | 317.61 | 315.03 | 0.992× |
| One MIN plus two grouped ordinary fields | 160.81 | 295.76 | **1.839×** |
| Three MIN/MAX fields | 87.79 | 292.88 | **3.336×** |
| SUM/AVG/COUNT control | 179.65 | 177.27 | 0.987× |

Each ratio compares a workload against itself, not interchangeable query/output
contracts. The targeted extrema improve substantially with close-to-flat wide
controls. No general, MariaDB, streaming or tail-latency gain is inferred.

## Single-row results: unfavorable evidence and investigation

Primary one-row runs use six 2,000-operation trials after 200 warmups:

| Workload | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Ordinary projection | 11,967 | 10,581 |
| One MIN | 9,238 | 9,756 |
| Three extrema | 9,337 | 9,171 |
| SUM/AVG/COUNT | 9,020 | 9,656 |

The ordinary-projection decrease was not dismissed. A longer unpinned repeat uses
the same compiled SQL/bindings and strict result contract for raw, with prebuilt
snekql queries and shared transactions. Ten 5,000-operation trials after 1,000
warmups per adapter/process, six B/C/B/C/B/C processes; adapters alternate order
by trial and initial order by process: **30 samples per adapter/revision**.

| Longer unpinned repeat | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| snekql | 11,827 | 9,914 |
| raw driver control | 30,883 | 31,178 |

The decrease persisted, so promotion was held while investigating. Isolated
resolution/compilation diagnostics did not show comparable CPU-cost growth. Two
additional public execution series used the same workload, warmup and trial
counts, but reversed revision order to C/B/C/B/C/B. They also record main-thread
CPU time. One pins the **process and inherited threads to logical CPU 2** using
`taskset -c 2`; the other retains normal affinity over all 28 CPUs.

| Additional series | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| CPU 2, reversed revision order | snekql | 12,091 | 12,095 |
| CPU 2, reversed revision order | raw | 34,471 | 33,881 |
| Unpinned, reversed revision order | snekql | 11,038 | 11,461 |
| Unpinned, reversed revision order | raw | 30,520 | 30,834 |

Pinned snekql main-thread CPU time: **75.537 → 75.515 µs/read**; unpinned reversed
series: **84.744 → 81.616 µs/read**. CPU 2 has sibling CPU 3 and reported maximum
frequency 5.3 GHz. Pinning is a changed measurement condition, **not exclusive
host control**. The pinned and unpinned series are separate, not pooled.

These checks do not support a consistent intrinsic ordinary-read slowdown, but
they do **not fully explain the original decrease or prove every deployment is
unaffected**. All unfavorable data remain published. No general point-read gain
or blanket absence-of-regression claim is made; the claim is the targeted wide
extrema improvement above.

Separate comparative processes after each primary timing process use ordinary
point reads, per-operation construction and per-read transactions: six rotating
adapter trials of 2,000 operations after 200 warmups. This is a distinct contract
from the shared-transaction follow-ups.

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 13,974 | 12,693 |
| snekql | 3,131 | 3,107 |
| SQLAlchemy | 3,214 | 3,409 |

Controls move; results are not normalized by their ratios.

## Separate memory and profiles

Tracemalloc retains 20 reads × 1,000 result rows, three samples/case/revision:

| Workload | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary projection | 12,765,539 → 12,765,539 | 12,841,443 → 12,841,443 |
| One MIN | 12,765,642 → 12,765,578 | 12,842,442 → 12,841,914 |
| Three extrema | 12,765,568 → 12,765,568 | 12,842,448 → 12,842,768 |
| SUM/AVG/COUNT | 10,585,347 → 10,585,347 | 10,662,195 → 10,662,195 |

Output retention and peaks are approximately unchanged. This is not total RSS or
isolated setup allocation. Resolved extrema allocate per-execution NULL closures
and bound-column partials; there is no persistent query or output-row cache.
Setup is included in the timing workloads.

Separate profiles consume 100 × 1,000 result rows:

| Diagnostic count | One MIN, B → C | Three extrema, B → C |
| --- | ---: | ---: |
| Structural protocol checks | 100,800 → 800 | 301,000 → 1,000 |
| Static attribute lookups | 100,700 → 700 | 300,900 → 900 |
| Column decodes | 300,000 → 300,000 | 300,000 → 300,000 |
| Final named-result materializations | 100,000 → 100,000 | 100,000 → 100,000 |

These counts support avoided dispatch, not skipped codecs or validation. Profile
durations are not used to estimate throughput gains.

## Validation and evidence

Eight new public cases pass on baseline and candidate: buffered/streamed extrema,
policy/dialect/policy-only extensions, empty inputs, changing validation on query
reuse, and SUM/AVG/COUNT value/type controls. Unsafe policy bypass, adoption of
dialect-only projection codecs, removal of NULL handling and validation bypass
are caught and reverted.

Focused SQLite/MariaDB aggregate, scalar and compiler coverage: **87 passed**.
Full local suite: **3,995 passed**, exit 0, 883.64s. Static/CI status is recorded in
the PR. No private-call-count or speed assertions enter CI.

Published **780 samples**:

- [288 primary timings](results/extrema-decoders-506/timing-trials.csv),
  [120 unpinned follow-ups](results/extrema-decoders-506/followup-trials.csv),
  [120 pinned follow-ups](results/extrema-decoders-506/pinned-trials.csv),
  [120 reversed unpinned follow-ups](results/extrema-decoders-506/reverse-trials.csv),
  [24 memory samples](results/extrema-decoders-506/memory-trials.csv),
  [probe provenance/commands](results/extrema-decoders-506/probe-manifest.json).
- [108 comparative trials](results/extrema-decoders-506/comparative-trials.csv) and
  [environment/session/command metadata](results/extrema-decoders-506/comparative-manifest.json).

Full validation finished before measurement. Owned timing, memory, profiles,
diagnostics and follow-ups ran sequentially. All retained measurement processes
exited zero with clean source trees. Discovery initially put group_by on a model
query; corrected to project before group_by, excluded before measurement.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave. Primary runs and unpinned
follow-ups have no affinity restriction; only the explicitly labeled series uses
CPU 2. No exclusive host control. Private Btrfs databases, SQLite WAL/NORMAL.
Visible-test checks before commands cannot prevent other work starting during a
run. Raw evidence is retained in `/home/crpier/.cache/snekql-506/` and discovery/
mutation logs in `/home/crpier/.cache/snekql-aggregate-next/`.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1` and a private
disk-backed `TMPDIR`. Save scripts outside source roots, run from the exact
worktrees above. Primary timing uses six fresh B/C alternating processes; memory
and profile modes run separately. After each primary timing process, run:

```bash
python -m benchmarks.compare --backend sqlite --workload point-read \
    --rows 2000 --operations 2000 --trials 6 --warmup 200
```

### Primary: `python probe.py timing`, `memory`, or `profile`

```python
import asyncio, cProfile, gc, json, os, platform, subprocess, sys, tempfile, time, tracemalloc
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_sqlite import seed
from pydantic import BaseModel


class Record(BaseModel):
    key: int | None
    email: str | None
    payload: str | None


from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


class First:
    pass


class Second:
    pass


class Third:
    pass


class Numbers(BaseModel):
    key: int | None
    mean: float | None
    count: int


def query(width, shape):
    q = sqlite.select(BenchUser).where(BenchUser.id.lte(width))
    if shape == "numbers":
        return (
            q.project(
                Numbers,
                key=BenchUser.id.sum(),
                mean=BenchUser.id.avg(),
                count=BenchUser.id.count(),
            )
            .group_by(BenchUser.id)
            .order_by(BenchUser.id.asc())
        )
    if shape == "three":
        return (
            q.project(
                Record,
                key=BenchUser.id.min(),
                email=BenchUser.email.max(),
                payload=BenchUser.payload.min(),
            )
            .group_by(BenchUser.id)
            .order_by(BenchUser.id.asc())
        )
    if shape == "one":
        return (
            q.project(
                Record,
                key=BenchUser.id.min(),
                email=BenchUser.email,
                payload=BenchUser.payload,
            )
            .group_by(BenchUser.id, BenchUser.email, BenchUser.payload)
            .order_by(BenchUser.id.asc())
        )
    return q.project(
        Record, key=BenchUser.id, email=BenchUser.email, payload=BenchUser.payload
    ).order_by(BenchUser.id.asc())


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
                for shape in ("plain", "one", "three", "numbers"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        if shape == "numbers":
                            assert (rows[0].key, rows[0].mean, rows[0].count) == (
                                1,
                                1.0,
                                1,
                            )
                            assert (rows[-1].key, rows[-1].mean, rows[-1].count) == (
                                width,
                                float(width),
                                1,
                            )
                        else:
                            assert (rows[0].key, rows[0].email, rows[0].payload) == (
                                1,
                                "user1@example.com",
                                "x" * 32,
                            )
                            assert (rows[-1].key, rows[-1].email, rows[-1].payload) == (
                                width,
                                f"user{width}@example.com",
                                "x" * 32,
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


asyncio.run(main())
```

### Follow-ups: `python followup.py PHASE_INDEX`

The script below adds CPU-time/affinity reporting to the original unpinned
follow-up. Use phases 0–5 with B/C order for the first series, C/B for the reversed
series, and `taskset -c 2 python followup.py PHASE_INDEX` with C/B for the pinned
series. Adapter order alternates by trial and phase.

```python
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from pydantic import BaseModel
from benchmarks._comparison_sqlite import seed
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


class Record(BaseModel):
    key: int | None
    email: str | None
    payload: str | None


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
            query = (
                sqlite.select(BenchUser)
                .where(BenchUser.id.lte(1))
                .project(
                    Record,
                    key=BenchUser.id,
                    email=BenchUser.email,
                    payload=BenchUser.payload,
                )
                .order_by(BenchUser.id.asc())
            )
            compiled = query.compile()

            async def snekql_read():
                rows = await tx.fetch_all(query)
                assert len(rows) == 1
                row = rows[0]
                assert (row.key, row.email, row.payload) == (
                    1,
                    "user1@example.com",
                    "x" * 32,
                )

            async def raw_read():
                async with raw.execute(compiled.sql, compiled.params) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
                row = Record.model_validate(
                    dict(zip(("key", "email", "payload"), rows[0], strict=True)),
                    strict=True,
                    by_alias=False,
                    by_name=True,
                )
                assert (row.key, row.email, row.payload) == (
                    1,
                    "user1@example.com",
                    "x" * 32,
                )

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
