# Execution-local scalar-subquery decoding — #504

Measured 2026-10-22 (UTC): merged baseline `f3fab4b` (including #503), initial
candidate `6a20f6a`, and final implementation `71f73f2`. These are incremental
comparisons, not multiplied previous gains.

## Change and semantic boundaries

Scalar-subquery outputs repeatedly inspected the inner query and entered general
selectable dispatch for each row. Exact built-in scalar nodes now resolve their
single-column wire decoder once per execution. A scalar's SQL NULL still returns
None before calling even a NOT NULL source codec. Nested scalar/CTE chains retain
source policy, column validation and skipped intermediate application validation.

The scalar-specific branch comes **after the existing ordinary-column fast path**.
Unknown/custom expressions retain general dispatch. No global/query cache,
dependency, driver, SQL rewrite, public API or runtime/checkpoint change is added.

## Final wide-read results

Private disk-backed SQLite, 2,000 seeded rows. Named results have three optional
fields (`key`, `email`, 32-byte `payload`). Scalar subqueries correlate an aliased
source's primary key with the outer row. Prebuilt queries, shared transactions,
ordered results; each read checks count, endpoints and expected NULL count.

Six alternating fresh processes B/C/B/C/B/C; six trials of 100 reads after ten
warmups per shape/process: **18 samples per shape/revision**, 1,000 rows/read.

| Shape | Baseline reads/s | Final reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control | 307.56 | 311.41 | 1.013× |
| One scalar field + two ordinary fields | 114.10 | 293.98 | **2.577×** |
| Three scalar fields | 53.27 | 276.20 | **5.185×** |
| One scalar field, half the subqueries empty | 138.03 | 309.63 | **2.243×** |

These SQLite buffered workloads show substantial improvements with a close-to-flat
ordinary projection control. No universal, MariaDB, streaming or tail-latency
speedup is inferred.

## Initial evidence and guard-order refinement

The initial implementation checked for scalar nodes before ordinary columns. Its
wide-read medians were:

| Shape | Baseline reads/s | Initial reads/s |
| --- | ---: | ---: |
| Ordinary projection | 308.88 | 311.71 |
| One scalar | 114.04 | 296.97 |
| Three scalars | 53.50 | 277.18 |
| Half-empty scalar | 139.04 | 307.83 |

However, single-row controls prompted investigation. All initial data are retained,
not replaced by the final series. Moving the scalar check behind the ordinary
fast path avoids adding that branch to ordinary-column dispatch. Tests and the
entire measurement sequence were rerun on the final source. This does **not**
isolate guard ordering as the cause of all observed control movement.

## Single-row measurements and longer controls

Primary single-row runs use six 2,000-operation trials after 200 warmups, with the
same prebuilt/shared-transaction contract. The half-empty workload has one present
row when width is one.

| Shape | Initial B → C ops/s | Final B → C ops/s |
| --- | ---: | ---: |
| Ordinary projection | 11,498 → 9,349 | 11,687 → 11,149 |
| One scalar | 7,419 → 9,312 | 7,592 → 9,339 |
| Three scalars | 6,233 → 6,504 | 5,705 → 7,198 |
| Half-empty case, one present row | 7,491 → 7,228 | 7,391 → 8,240 |

The initial ordinary-projection decrease received a longer follow-up, then the
same follow-up was repeated on the final source: six alternating fresh processes,
ten 5,000-operation trials after 1,000 warmups per adapter/process. Adapter order
alternates each trial and initial order alternates by process: **30 samples per
adapter/revision/series**. Raw uses the same compiled SQL, bindings and strict
named-result validator, but not the full query/runtime contract.

| Ordinary-projection follow-up | Initial B → C ops/s | Final B → C ops/s |
| --- | ---: | ---: |
| snekql | 11,565 → 10,837 | 11,270 → 11,496 |
| raw driver control | 30,228 → 30,064 | 29,768 → 30,824 |

The initial decrease persisted at a smaller magnitude before refinement. The
final longer run does not reproduce it, and its small increase moves with raw.
**No general point-read gain or blanket absence-of-regression claim is made.**

Independent comparative processes run after each primary timing process closes
its database: ordinary point reads with per-operation construction and per-read
transactions, six rotating adapter trials of 2,000 operations after 200 warmups.
These are distinct contracts from the prebuilt/shared-transaction probes.

| Adapter | Initial B → C ops/s | Final B → C ops/s |
| --- | ---: | ---: |
| raw | 14,279 → 14,016 | 14,054 → 13,630 |
| snekql | 3,046 → 2,984 | 3,363 → 3,314 |
| SQLAlchemy | 3,319 → 3,273 | 3,282 → 3,334 |

Controls move; results are not normalized by their ratios. Unfavorable data remain
published alongside the targeted improvements.

## Separate memory and profiles

Final tracemalloc series retain 20 reads × 1,000 rows, three samples/shape/revision:

| Shape | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary projection | 12,765,539 → 12,765,539 | 12,841,459 → 12,841,459 |
| One scalar | 12,765,623 → 12,765,623 | 12,842,751 → 12,842,223 |
| Three scalars | 12,765,791 → 12,765,791 | 12,842,935 → 12,843,255 |
| Half-empty scalar | 12,765,598 → 12,765,598 | 12,842,886 → 12,842,358 |

Returned-output retention is unchanged and traced peaks are approximately unchanged.
This is not total RSS or isolated setup allocation. Resolution creates per-execution
NULL-handling closures and source decoder partials; setup is included in timings,
not retained on a query or returned row. Initial memory samples are also published.

Final profiles consume 100 × 1,000 rows separately from timings:

| Diagnostic count | One scalar, B → C | Three scalars, B → C |
| --- | ---: | ---: |
| Structural protocol checks | 200,300 → 300 | 600,300 → 300 |
| Static attribute lookups | 200,200 → 200 | 600,200 → 200 |
| Single-column subquery checks | 100,100 → 200 | 300,300 → 600 |
| Column decodes | 300,000 → 300,000 | 300,000 → 300,000 |
| Final named-result materializations | 100,000 → 100,000 | 100,000 → 100,000 |

Counts corroborate avoided dispatch and preserved decoding/validation work.
Instrumented durations are not the throughput estimates; discovery and initial
profiles are not pooled with this final profile pair.

## Validation and evidence

Ten public regression cases pass on baseline and candidate: buffered/streamed
scalar reads, no-match NULLs, policy/dialect/policy-only extensions, validation
changes on query reuse, and scalar → CTE output → scalar chains without intermediate
application validation. Unsafe NULL, validation and extension bypasses fail;
mutations restored. An initial test used an out-of-scope predicate and was corrected
to an explicit column correlation before baseline/candidate validation.

Focused scalar/correlation/provenance/CTE/recursive coverage: **87 passed**. Initial
full suite: **3,987 passed**, 1035.40s. Final full suite: **3,987 passed**, exit 0,
1026.76s. Static/CI status is recorded in the PR. No private-call-count or speed
assertions enter CI.

Published **1,080 samples**, split rather than pooled:

- Initial: [288 timing](results/scalar-decoders-504/initial/timing-trials.csv),
  [120 follow-up](results/scalar-decoders-504/initial/followup-trials.csv),
  [24 memory](results/scalar-decoders-504/initial/memory-trials.csv),
  [108 comparative](results/scalar-decoders-504/initial/comparative-trials.csv),
  [probe provenance](results/scalar-decoders-504/initial/probe-manifest.json),
  [comparative environment/commands](results/scalar-decoders-504/initial/comparative-manifest.json).
- Final: [288 timing](results/scalar-decoders-504/final/timing-trials.csv),
  [120 follow-up](results/scalar-decoders-504/final/followup-trials.csv),
  [24 memory](results/scalar-decoders-504/final/memory-trials.csv),
  [108 comparative](results/scalar-decoders-504/final/comparative-trials.csv),
  [probe provenance](results/scalar-decoders-504/final/probe-manifest.json),
  [comparative environment/commands](results/scalar-decoders-504/final/comparative-manifest.json).

Each full suite finished before its measurements. Owned timing, memory, profiles
and follow-ups ran sequentially. All retained measurement processes exited zero
with clean source trees. Two preflight mistakes are excluded: a nonnullable result
field for a potentially NULL scalar, and a projected `id` label shadowing the
ORDER BY column in the half-empty case. The corrected probe uses a `key` result
label. Failed preflight scripts/logs and all successful raw evidence are retained
under `/home/crpier/.cache/snekql-scalar-next/` and `/home/crpier/.cache/snekql-504/`.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave, no pinning or exclusive
host control. Private Btrfs disk-backed databases, SQLite WAL/NORMAL. Visible-test
checks before commands do not prevent other work starting during measurements.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1` and a private
disk-backed `TMPDIR`. Save scripts outside source roots and run from the exact
worktrees above. Run timing in six alternating baseline/candidate processes.
Memory/profile modes run separately. After each primary timing process, run:

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


def query(width, shape):
    peer = sqlite.alias(BenchUser, First, name="peer")
    fields = []
    for index, column in enumerate((BenchUser.id, BenchUser.email, BenchUser.payload)):
        if shape == "plain" or (index > 0 and shape != "three"):
            fields.append(column)
            continue
        inner = sqlite.select(peer.column(column)).where(
            peer.column(BenchUser.id).eq_col(BenchUser.id)
        )
        if shape == "missing":
            inner = inner.where(peer.column(BenchUser.id).lte(max(1, width // 2)))
        fields.append(sqlite.scalar(inner))
    return (
        sqlite.select(BenchUser)
        .where(BenchUser.id.lte(width))
        .project(Record, key=fields[0], email=fields[1], payload=fields[2])
        .order_by(BenchUser.id.asc())
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
                for shape in ("plain", "one", "three", "missing"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        assert (rows[0].key, rows[0].email, rows[0].payload) == (
                            1,
                            "user1@example.com",
                            "x" * 32,
                        ), (width, shape, rows[0], q.compile())
                        assert (rows[-1].key, rows[-1].email, rows[-1].payload) == (
                            None if shape == "missing" and width > 1 else width,
                            f"user{width}@example.com",
                            "x" * 32,
                        )
                        assert sum(row.key is None for row in rows) == (
                            width - max(1, width // 2) if shape == "missing" else 0
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

### Follow-up: `python followup.py PHASE_INDEX`

Phase indices 0–5 alternate initial adapter order.

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
                    start = time.perf_counter()
                    for _ in range(5000):
                        await op()
                    elapsed = time.perf_counter() - start
                    samples.append(
                        dict(
                            adapter=adapter,
                            trial=trial + 1,
                            operations=5000,
                            seconds=elapsed,
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
                samples=samples,
            )
        )
    )


asyncio.run(main())
```
