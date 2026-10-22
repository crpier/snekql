# Whole-source joined CTE decoding — #502

Measured 2026-10-22: merged baseline `40b2cf7` (including #501) versus clean
implementation `8da56cc`. This is an incremental comparison, not multiplied
previous gains.

## Change and constraints

Whole-source joins retained per-row general dispatch for named CTE payloads, even
after explicit derived projections gained execution-local resolution in #501.

The execution plan now retains decoder tuples for named source spans. The same
`JoinedRowShape` still supplies SQL expansion and row decoding; presence witnesses,
span widths and ordering do not change. Physical models keep normal column decoding
and descriptor assignment. Named payloads use the existing policy-aware resolver;
absent rows return before any payload decoder or application validator runs.
Definition-local NULL extension remains the responsibility of the original wire
source. Each present named source validates its own final application model, not
intermediate CTE result models.

There is no global/shared-definition cache, dependency change, new public API,
backend import or runtime/checkpoint change. Resolution is per execution, so query
reuse retains the current validation policy. Physical-only joins keep an empty
decoder matrix. A plan carries one additional reference; named joins allocate
per-execution decoder tuples/partials rather than retaining them on a query.

## Wide-read measurements

Private disk-backed SQLite database, 2,000 seeded rows, three fields (`id`, `email`,
32-byte `payload`). Prebuilt queries and shared transactions. Each read checks
count, first/last fields, paired values and the number of present named rows.

Six alternating fresh processes B/C/B/C/B/C; six 100-operation trials after ten
warmups per shape/process, **18 samples per shape/revision**, 1,000 rows/read.

| Shape | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Physical-only join control | 138.09 | 135.84 | 0.984× |
| Physical model + whole named CTE | 41.70 | 128.00 | **3.070×** |
| LEFT join, half the named rows missing | 71.57 | 166.73 | **2.330×** |
| Explicit named projection over a CTE join | 300.87 | 299.31 | 0.995× |

These controls have different output contracts and are not absolute alternatives:
the physical-only join constructs two physical models, the named join constructs
a physical model plus a Pydantic result, and the explicit projection constructs
only the Pydantic result. Ratios compare each workload against itself. Wide controls
are close to unchanged while the targeted named-source paths improve substantially.
No MariaDB, streaming or universal speedup is inferred from SQLite buffered timing.

## Single-row results, controls and follow-up

The same processes also read one row, six 2,000-operation trials after 200 warmups:

| Shape | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Physical-only join | 6,874 | 6,487 |
| Whole named CTE join | 4,564 | 5,116 |
| LEFT join (one present row) | 4,209 | 4,219 |
| Explicit named projection | 6,582 | 6,976 |

The physical-only decrease prompted longer control repeats: six alternating fresh
processes, ten 5,000-operation trials after 1,000 warmups per shape/process,
**30 samples per shape/revision**. Physical then explicit shape order is fixed
within a process, as in the first series.

| Follow-up control | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Physical-only join | 7,242 | 7,859 |
| Explicit named projection | 7,741 | 6,895 |

The original physical-only decrease did not reproduce, but the explicit control
now decreases. Both series are retained. These direction changes make single-row
measurements inconclusive; they are not evidence that every query is unaffected.
**No general single-row gain is claimed.**

Separate comparative processes follow each primary timing process after its
database closes: ordinary point reads, per-operation construction and per-read
transactions, six rotating adapter trials of 2,000 operations after 200 warmups.
This is a distinct contract from the prebuilt/shared-transaction probes above.

| Adapter | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| raw | 12,316 | 13,901 |
| snekql | 2,802 | 2,976 |
| SQLAlchemy | 3,063 | 2,975 |

These moving controls do not establish an isolated general runtime gain. Results
are not normalized by control ratios, and unfavorable measurements are not dropped.

## Separate memory and profiles

Tracemalloc retains 20 reads × 1,000 rows, three samples per shape/revision:

| Shape | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Physical join | 13,823,739 → 13,823,739 | 13,934,027 → 13,934,067 |
| Whole named join | 20,234,524 → 20,233,894 | 20,343,492 → 20,343,862 |
| LEFT named join | 13,944,156 → 13,943,904 | 14,053,348 → 14,054,096 |
| Explicit projection | 12,765,674 → 12,765,674 | 12,841,794 → 12,841,802 |

Returned-output retention and traced peaks are approximately unchanged. This is
not total RSS or an isolated setup-allocation measurement. Per-execution setup
costs are included in timings; the plan adds a reference and named-source decoder
matrices/partials, with no persistent per-query or per-returned-row cache.

Separate whole-named-join profiles consume 100 × 1,000 rows:

- Structural protocol checks: **901,900 → 1,900**.
- Static attribute lookups: **600,400 → 300**.
- Output-slot decode calls: **300,000 → 0**.
- **600,000 column decodes**, **300,000 model assignments**, **300,000 descriptor
  assignments** and **100,000 final named-result materializations** remain.

Counts corroborate avoided dispatch, not skipped decoding or validation. Profile
timing is not used as the throughput estimate.

## Validation and evidence

Eight new public cases pass on baseline and candidate: buffered/streamed whole
named joins, nested/aliased CTEs, custom policy/dialect/policy-only extensions,
missing named rows, physical-model values and changing column validation on query
reuse. Existing mixed physical/named all-NULL payload tests cover presence markers
and span order. Unsafe loss of absence handling, all-NULL/presence confusion and
validation bypass are caught and reverted.

Focused query/recursive/derived/join-shape coverage: **95 passed**. Full local
suite: **3,977 passed**, exit 0, 1070.63s. Static and CI status is recorded in the PR.
No private-call-count or speed assertions enter CI.

Published **540 samples**:

- [288 targeted timing samples](results/joined-derived-502/timing-trials.csv),
  [120 follow-up samples](results/joined-derived-502/followup-trials.csv),
  [24 memory samples](results/joined-derived-502/memory-trials.csv), and
  [probe provenance/commands](results/joined-derived-502/probe-manifest.json).
- [108 comparative samples](results/joined-derived-502/comparative-trials.csv) and
  [environment/session/command metadata](results/joined-derived-502/comparative-manifest.json).

Full validation finished before timings; owned timing, memory, profiles and
follow-ups ran sequentially. All retained measurement commands exited zero with
clean source trees. An initial discovery preflight incorrectly used `eq` instead
of `eq_col` for a join operand and failed before measurement; it was corrected and
excluded. Discovery profiles are separate from the comparative samples.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave, no pinning or exclusive
host control. Private Btrfs disk-backed databases, SQLite WAL/NORMAL. The runner
waits for visible Python tests before commands; that does not prevent other work
starting during a measurement. Raw reports/profiles remain in
`/home/crpier/.cache/snekql-502/`; discovery/mutation logs are in
`/home/crpier/.cache/snekql-joined-next/`.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1` and a private
disk-backed `TMPDIR`. Save scripts outside source roots; run from the exact
worktrees above. Run timing in six alternating baseline/candidate processes.
Memory and profile modes must run separately, not concurrently with timing/tests.
The separate comparative command after each primary timing process is:

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
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


class First:
    pass


class Second:
    pass


class Third:
    pass


def query(width, shape):
    if shape == "physical":
        peer = sqlite.alias(BenchUser, First, name="peer")
        return (
            sqlite.select(BenchUser)
            .join(peer, on=BenchUser.id.eq_col(peer.column(BenchUser.id)))
            .where(BenchUser.id.lte(width))
            .order_by(BenchUser.id.asc())
        )
    tokens = [
        BenchUser.id.label("id"),
        BenchUser.email.label("email"),
        BenchUser.payload.label("payload"),
    ]
    source = sqlite.select(BenchUser)
    if shape == "left":
        source = source.where(BenchUser.id.lte(max(1, width // 2)))
    definition = source.project(
        Record, id=tokens[0], email=tokens[1], payload=tokens[2]
    ).cte(First, name="readings")
    refs = [definition.column(token) for token in tokens]
    q = sqlite.select(BenchUser)
    q = (
        q.left_join(definition, on=BenchUser.id.eq_col(refs[0]))
        if shape == "left"
        else q.join(definition, on=BenchUser.id.eq_col(refs[0]))
    )
    q = q.where(BenchUser.id.lte(width)).order_by(BenchUser.id.asc())
    if shape == "explicit":
        q = q.project(Record, id=refs[0], email=refs[1], payload=refs[2])
    return q


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
                for shape in ("physical", "joined", "left", "explicit"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        records = (
                            rows if shape == "explicit" else [pair[0] for pair in rows]
                        )
                        assert (
                            records[0].id,
                            records[0].email,
                            records[0].payload,
                        ) == (1, "user1@example.com", "x" * 32)
                        assert (
                            records[-1].id,
                            records[-1].email,
                            records[-1].payload,
                        ) == (width, f"user{width}@example.com", "x" * 32)
                        if shape != "explicit":
                            present = max(1, width // 2) if shape == "left" else width
                            assert sum(b is not None for a, b in rows) == present
                            assert all(
                                (a.id, a.email, a.payload) == (b.id, b.email, b.payload)
                                for a, b in rows
                                if b is not None
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

### Follow-up: `python followup.py timing`

```python
import asyncio, cProfile, gc, json, os, platform, subprocess, sys, tempfile, time, tracemalloc
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_sqlite import seed
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


class First:
    pass


class Second:
    pass


class Third:
    pass


def query(width, shape):
    if shape == "physical":
        peer = sqlite.alias(BenchUser, First, name="peer")
        return (
            sqlite.select(BenchUser)
            .join(peer, on=BenchUser.id.eq_col(peer.column(BenchUser.id)))
            .where(BenchUser.id.lte(width))
            .order_by(BenchUser.id.asc())
        )
    tokens = [
        BenchUser.id.label("id"),
        BenchUser.email.label("email"),
        BenchUser.payload.label("payload"),
    ]
    source = sqlite.select(BenchUser)
    if shape == "left":
        source = source.where(BenchUser.id.lte(max(1, width // 2)))
    definition = source.project(
        Record, id=tokens[0], email=tokens[1], payload=tokens[2]
    ).cte(First, name="readings")
    refs = [definition.column(token) for token in tokens]
    q = sqlite.select(BenchUser)
    q = (
        q.left_join(definition, on=BenchUser.id.eq_col(refs[0]))
        if shape == "left"
        else q.join(definition, on=BenchUser.id.eq_col(refs[0]))
    )
    q = q.where(BenchUser.id.lte(width)).order_by(BenchUser.id.asc())
    if shape == "explicit":
        q = q.project(Record, id=refs[0], email=refs[1], payload=refs[2])
    return q


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
            for width in (1,):
                for shape in ("physical", "explicit"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        records = (
                            rows if shape == "explicit" else [pair[0] for pair in rows]
                        )
                        assert (
                            records[0].id,
                            records[0].email,
                            records[0].payload,
                        ) == (1, "user1@example.com", "x" * 32)
                        assert (
                            records[-1].id,
                            records[-1].email,
                            records[-1].payload,
                        ) == (width, f"user{width}@example.com", "x" * 32)
                        if shape != "explicit":
                            present = max(1, width // 2) if shape == "left" else width
                            assert sum(b is not None for a, b in rows) == present
                            assert all(
                                (a.id, a.email, a.payload) == (b.id, b.email, b.payload)
                                for a, b in rows
                                if b is not None
                            )
                        return rows

                    for _ in range(1000):
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
                    for trial in range(10):
                        result = dict(
                            shape=shape, rows_per_operation=width, trial=trial + 1
                        )
                        if mode == "timing":
                            operations = 5000
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
