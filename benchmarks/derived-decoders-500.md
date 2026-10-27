# Execution-local derived-output decoding — #500

Measured 2026-10-22: merged baseline `dafc719` (including #499) versus clean
implementation `79d6e6e`. This is an incremental comparison, not a multiplication
of earlier gains.

## Change and scope

Ordinary projections already resolve column decoders once per execution. Built-in
CTE references instead repeatedly entered general protocol dispatch, followed an
output slot, and repeated dispatch on its source for every field of every row.

`resolve_projection_decoder` now follows **exact built-in CTE output references**
to their original wire sources. Each definition retains its own nullable-owner
context, and a missing consuming reference retains its outer NULL extension.
Backend mismatch keeps the old deferred error path rather than raising during
resolution of an empty or unmatched read.

The final application result still validates; intermediate application models do
not. Column validation, custom policy/dialect codecs and alias identity remain.
Resolution is per execution: no shared-definition/global capability cache, new
public API, dependency change or direct logical-validation shortcut.

This targets top-level and explicit derived projections using the existing
resolver. Whole-source joined CTE materialization still has a separate general
path. Unknown/custom expressions retain their prior dispatch. This is not a
promise that every CTE-containing query gets the measured improvement.

## Targeted wide reads

Private disk-backed SQLite database, 2,000 seeded rows, three fields (`id`, `email`,
32-byte `payload`). Prebuilt queries, one shared transaction, ordered results.
The nested case has three consecutive SQL definitions. Each operation checks its
row count and the first/last record values.

Six fresh processes B/C/B/C/B/C, six trials of 100 reads after ten warmups per
shape/process: **18 samples per shape/revision**, 1,000 rows per read.

| Shape | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection control | 303.26 | 305.53 | 1.007× |
| One CTE | 50.65 | 303.23 | **5.987×** |
| Three nested CTEs | 43.78 | 301.36 | **6.883×** |

These CTE workloads reach approximately ordinary-projection throughput. This
establishes a large improvement for the measured SQLite buffered-read shapes,
not a MariaDB, streaming, latency-tail or universal performance guarantee.

## Single-row results and independent controls

The same processes also read one row: six 2,000-operation trials after 200 warmups,
with the same prebuilt/shared-transaction contract.

| Shape | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| Ordinary projection | 9,717 | 9,373 | 0.965× |
| One CTE | 6,416 | 6,669 | 1.039× |
| Three nested CTEs | 4,860 | 5,407 | 1.113× |

A separate comparative process follows each targeted timing process, after its
database has closed: 2,000 rows, six rotating adapter trials of 2,000 operations,
200 warmups. This uses **ordinary named projections, per-operation construction
and per-read transactions**, not the CTE/shared-transaction contract above.

| Adapter | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| raw | 11,837 | 12,504 | 1.056× |
| snekql | 2,802 | 2,966 | 1.059× |
| SQLAlchemy | 2,711 | 2,893 | 1.067× |

Single-row results are mixed and the comparative controls move together. The
ordinary projection decrease is retained, not discarded or normalized away.
**No general point-read improvement is attributed to this change.** The much
larger wide-CTE result has an approximately flat ordinary-projection control.

## Separate memory and profiles

Tracemalloc retains 20 reads × 1,000 rows, three samples per shape/revision:

| Shape | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Ordinary projection | 12,765,538 → 12,765,538 | 12,841,426 → 12,841,426 |
| One CTE | 12,765,632 → 12,765,632 | 12,842,720 → 12,841,744 |
| Nested CTEs | 12,766,119 → 12,766,119 | 12,843,263 → 12,842,287 |

Retained output memory is unchanged; peak differences are negligible. This is not
a total-RSS or isolated setup-memory measurement. Decoder resolution walks the
chain for each execution and may create NULL-handling closures; it does not retain
new state on the reusable query or its output slots. Single-row timings include
this per-execution setup.

Separate profiles consume 100 × 1,000 rows after warmup:

| Diagnostic count | One CTE, B → C | Nested CTEs, B → C |
| --- | ---: | ---: |
| Structural protocol instance checks | 901,600 → 1,600 | 1,503,400 → 3,400 |
| `getattr_static` | 600,200 → 200 | 600,200 → 200 |
| Output-slot decode calls | 300,000 → 0 | 900,000 → 0 |
| Column `Attr.decode` | 300,000 → 300,000 | 300,000 → 300,000 |
| Final named-result materialization | 100,000 → 100,000 | 100,000 → 100,000 |

These counts corroborate avoided dispatch and retained column/final-model work.
Instrumented time is not used to estimate throughput gains. The initial discovery
profile used a different CTE construction and is not pooled with these comparisons.

## Validation and evidence

Twelve public regression cases pass on both baseline and candidate: buffered and
streamed nested/aliased reads, policy/dialect/policy-only extension precedence,
final-only application validation, query reuse with changing validation policy,
and definition-local versus consumer-local NULL extension. Unsafe extension bypass,
validation bypass, and loss of either NULL context are caught; mutations restored.

Focused public query/CTE/recursive/extension coverage: **79 passed**. Full local
suite: **3,969 passed**, exit 0, 893.53s. Static and CI status is recorded in the PR.
No speed or private-call-count assertions enter CI.

Published **342 samples**:

- [216 targeted trials](results/derived-decoders-500/timing-trials.csv),
  [18 memory samples](results/derived-decoders-500/memory-trials.csv), and
  [probe provenance/commands](results/derived-decoders-500/probe-manifest.json).
- [108 comparative trials](results/derived-decoders-500/comparative-trials.csv) and
  [environment/session/command metadata](results/derived-decoders-500/comparative-manifest.json).

All retained commands exited zero with clean source trees. Full validation
finished before timings began; owned timing, memory and profile commands ran
sequentially. The runner checks for visible Python test processes before each
command, but this does not establish exclusive host control.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave, no affinity pinning.
Private Btrfs disk-backed databases, SQLite WAL/NORMAL. No dependency changes.
Raw reports/profiles remain in `/home/crpier/.cache/snekql-500/`; initial discovery
and mutation logs are in `/home/crpier/.cache/snekql-derived-next/`.

## Reproduction

Use identical dependencies, `PYTHON_CONTEXT_AWARE_WARNINGS=1` and a private
disk-backed `TMPDIR`. Save the script outside source roots and run from the exact
worktrees above: `python probe.py timing`, `python probe.py memory`, then
`python probe.py profile`, never overlapping these modes. Each mode creates its
own database and warms the selected cases. Repeat timing in six fresh alternating
baseline/candidate processes. Run the comparative command separately after each:

```bash
python -m benchmarks.compare --backend sqlite --workload point-read \
    --rows 2000 --operations 2000 --trials 6 --warmup 200
```

### Targeted probe

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
    tokens = [
        BenchUser.id.label("id"),
        BenchUser.email.label("email"),
        BenchUser.payload.label("payload"),
    ]
    q = (
        sqlite.select(BenchUser)
        .where(BenchUser.id.lte(width))
        .project(Record, id=tokens[0], email=tokens[1], payload=tokens[2])
    )
    if shape == "projection":
        return q.order_by(BenchUser.id.asc())
    definition = q.cte(First, name="first_readings")
    refs = [definition.column(token) for token in tokens]
    if shape == "nested":
        for role, name in ((Second, "second_readings"), (Third, "third_readings")):
            tokens = [
                ref.label(label)
                for ref, label in zip(refs, ("id", "email", "payload"), strict=True)
            ]
            definition = (
                sqlite.select(definition)
                .project(Record, id=tokens[0], email=tokens[1], payload=tokens[2])
                .cte(role, name=name)
            )
            refs = [definition.column(token) for token in tokens]
    return sqlite.select(definition).order_by(refs[0].asc())


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
                for shape in ("projection", "cte", "nested"):
                    q = query(width, shape)

                    async def read():
                        rows = await tx.fetch_all(q)
                        assert len(rows) == width
                        assert (rows[0].id, rows[0].email, rows[0].payload) == (
                            1,
                            "user1@example.com",
                            "x" * 32,
                        )
                        assert (rows[-1].id, rows[-1].email, rows[-1].payload) == (
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
