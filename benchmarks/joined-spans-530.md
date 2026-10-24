# Joined span endpoints — #530 investigation, shelved

Measured 2026-10-24 UTC. Baseline **`a89f8c3`** (merged #529), experimental candidate
**`ad04cd1`**. The candidate was **reverted** before this report was submitted.
**No production optimization is proposed.** Candidate commit remains in the PR
history and its [patch](results/joined-spans-530/candidate.patch) is retained.

## Hypothesis and decision

Joined row decoding computes `offset + shape.width` for every source in every
row. The candidate adds an exclusive `stop` slot to each private row span,
resolved during field expansion, and slices `row[offset:stop]`. Source shapes,
presence witnesses, decoders, setters, validation and final contracts remain.
There is no global cache, but a two-source plan retains two additional slots.

The removed work is real: the physical-join profile eliminates **200,000 width
property calls** per 100 × 1,000 rows. Nevertheless, physical/derived throughput
did not show a sufficiently repeatable improvement, one-row results include
regressions, and plan memory increases. LEFT joins showed a small repeatable
benefit, explicitly retained below; that does not justify a general claim.

**Decision: shelve this version**, rather than ship on diagnostic call counts or
select only the favorable workload. This is a performance gate, not a claim that
precomputed spans can never help. No full candidate-suite run/release validation
was pursued after the evidence gate failed; candidate validation was focused
behavioral/static checking. The report PR's CI validates the restored code.

## Protocol

Identical dependencies, clean measured worktrees. Private disk-backed SQLite,
2,000 standard `BenchUser` rows (integer ID, email, 32-byte payload). Prebuilt
queries, shared transaction, buffered reads; not durable-commit latency or
MariaDB/streaming evidence.

Four workloads:

- **Physical:** model joined to a physical alias, returning two model rows.
- **Derived:** model joined to a named CTE, returning model/named pairs.
- **LEFT:** same derived join, half the wide result missing its right source.
- **Explicit control:** join projected into one named result, without whole-row
  joined materialization.

Each read buffers all results, checks count/endpoints and counts right-source
presence for joined results. Unlike the discovery probe, it does **not** read
all attributes of every returned pair; this avoids conflating bulk attribute
consumption with the targeted span work. The presence count is still included.

Six alternating processes per series: initial **B/C**, reversed **C/B**, then
separate **C/B pinned to CPU 2**. Per process: six trials × 100 operations after
ten warmups for 1,000 rows; six × 2,000 after 200 warmups for one row.
**18 samples/workload/revision/series**. All medians below are ops/s.
No raw normalization, pooled-series inference or exclusive host control.

## Wide results, 1,000 rows/operation

| Series | Workload | Baseline | Candidate | Ratio |
| --- | --- | ---: | ---: | ---: |
| Initial B/C | Physical | 141.62 | 143.03 | 1.010× |
| Initial B/C | Derived | 124.92 | 125.70 | 1.006× |
| Initial B/C | LEFT | 158.76 | 164.37 | 1.035× |
| Initial B/C | Explicit control | 271.66 | 262.81 | 0.967× |
| Reversed C/B | Physical | 150.46 | 150.88 | 1.003× |
| Reversed C/B | Derived | 134.36 | 132.13 | 0.983× |
| Reversed C/B | LEFT | 167.39 | 169.58 | 1.013× |
| Reversed C/B | Explicit control | 288.68 | 292.07 | 1.012× |
| Pinned C/B | Physical | 153.22 | 152.79 | 0.997× |
| Pinned C/B | Derived | 133.47 | 134.76 | 1.010× |
| Pinned C/B | LEFT | 167.75 | 172.46 | 1.028× |
| Pinned C/B | Explicit control | 291.40 | 295.31 | 1.013× |

LEFT's ~1.3–3.5% improvements are real observations, not discarded. Physical
results are near-flat and derived results change direction. Controls move too;
these are not uncertainty bounds or proof of causal effects. CPU affinity does
not establish a scheduling explanation for differences.

## One-row results

| Series | Workload | Baseline | Candidate |
| --- | --- | ---: | ---: |
| Initial B/C | Physical | 5,958 | 5,502 |
| Initial B/C | Derived | 3,907 | 3,992 |
| Initial B/C | LEFT | 3,977 | 3,611 |
| Initial B/C | Explicit control | 5,425 | 5,916 |
| Reversed C/B | Physical | 6,506 | 6,081 |
| Reversed C/B | Derived | 4,279 | 4,616 |
| Reversed C/B | LEFT | 3,722 | 3,715 |
| Reversed C/B | Explicit control | 7,188 | 6,086 |
| Pinned C/B | Physical | 8,338 | 8,170 |
| Pinned C/B | Derived | 5,618 | 5,488 |
| Pinned C/B | LEFT | 5,302 | 5,205 |
| Pinned C/B | Explicit control | 8,133 | 8,028 |

Pinned targets decline ~1.8–2.3%, explicit control ~1.3%. Large unpinned changes
remain unexplained. No claim that all declines are caused by the candidate, but
no blanket non-regression or isolated point-read improvement either.

## Plan setup and retained state

Separate diagnostic compiles internal execution plans to retain the metadata
that public SQL compilation does not expose. This is a **private benchmark
probe**, not an internal-call-count test or new application seam. Six alternating
B/C processes; per workload three trials × 1,000 compilations after 100 warmups;
separate tracemalloc retains 200 plans/trial. **Nine samples/shape/revision**.

| Workload | Compile plans/s B → C | Retained bytes, 200 plans B → C |
| --- | ---: | ---: |
| Physical | 17,551.93 → 17,717.30 | 267,856 → 271,056 |
| Derived | 10,874.66 → 10,925.66 | 597,932 → 598,864 |
| LEFT | 9,665.52 → 9,675.79 | 597,451 → 602,667 |
| Explicit control | 15,207.10 → 15,252.07 | 354,856 → 354,856 |

The physical plan's **+3,200 bytes / 200 plans = +16 bytes/plan** matches the two
added slots for this small-width fixture (~1.2% plan-retention cost). Other plan
measurements include strings/shared metadata and vary; do not infer exactly 16
bytes for arbitrary source counts/widths or subtract that figure from every
measurement. Compile throughput was approximately flat/slightly higher in this
series, not evidence of a general setup win. Full process RSS/startup not measured.

## Result retention and profiles

Separate output-memory probes retain 20 × 1,000 rows, three trials/shape/revision.

| Workload | Retained bytes B → C | Peak bytes B → C |
| --- | ---: | ---: |
| Physical | 13,823,739 → 13,823,739 | 13,926,875 → 13,926,891 |
| Derived | 20,234,286 → 20,234,223 | 20,337,590 → 20,337,543 |
| LEFT | 13,943,715 → 13,943,841 | 14,047,235 → 14,047,377 |
| Explicit | 12,765,674 → 12,765,674 | 12,841,802 → 12,841,802 |

Output retention essentially unchanged; these are traced allocations, not
native buffers or RSS. The extra plan state is not a per-result-row cost.

Physical join profile, 100 reads × 1,000 rows:

| Count | Baseline → Candidate |
| --- | ---: |
| Width property calls | **200,000 → 0** |
| Ordered model materializations | 200,000 → 200,000 |
| Column decodes | 600,000 → 600,000 |
| Model assignments | 600,000 → 600,000 |
| Descriptor assignments | 600,000 → 600,000 |

Profile time is diagnostic, not throughput. Eliminating calls is not sufficient
justification to deploy the candidate.

## Behavioral checks, exclusions and provenance

Before implementation, the existing **16 public joined-row shape regressions**
passed on baseline; candidate passed the same tests. They cover SQLite/MariaDB
buffered/streamed and one/optional reads, physical/named/alias spans, all-NULL
matched rows versus absence, ordering and hidden-witness name collisions.
Truncating each retained span caused **16 errors**; mutation restored.
**55 focused cases passed**, including derived policies, whole-model behavior
and named projections. Candidate Ruff/format/ty/whitespace checks passed.
No speed/private-call-count assertions added to CI.

Two harness preflights are retained and excluded:

1. A format-check failure prevented the intended candidate commit, but the next
   shell command still launched the runner. Owned runner/probe were stopped;
   that initial launch's artifacts were excluded. Formatting/commit completed
   before restarting all measured primary runs on clean revisions.
2. The setup probe imported a standalone script whose unguarded `main` expected
   an argument, raising `IndexError`. Added a `__main__` guard and reran setup.
   Earlier command-line timing/profile runs are unaffected. The manifest retains
   the failed setup attempt separately; valid samples are not silently dropped.

Owned tests/timings/profiles/memory ran sequentially. Host not exclusively
controlled. Published **960 sample records**: 288 initial, 288 reverse, 288 pinned,
72 combined setup/plan-memory records, 24 output-memory records. No comparative
adapter benchmark was added after deciding not to ship the candidate.

- [Commands/revision metadata](results/joined-spans-530/manifest.json)
- [Initial trials](results/joined-spans-530/timing-trials.csv)
- [Reverse trials](results/joined-spans-530/reverse-trials.csv)
- [Pinned trials](results/joined-spans-530/pinned-trials.csv)
- [Setup/plan memory](results/joined-spans-530/setup-trials.csv)
- [Output memory](results/joined-spans-530/memory-trials.csv)
- [Reverted candidate patch](results/joined-spans-530/candidate.patch)

Raw evidence `/home/crpier/.cache/snekql-530/`; initial profile and behavior logs
`/home/crpier/.cache/snekql-span-next/`. Excluded starts retained separately.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1;
i7-14700F/28 logical CPUs, powersave, private Btrfs databases, SQLite WAL/NORMAL.
Only the pinned series uses CPU 2.

## Reproduction

Use clean baseline/candidate worktrees with identical dependencies. Candidate
commit is retained in this PR's history; alternatively apply the included patch
to baseline and commit it locally. Save scripts outside worktrees, with
`PYTHON_CONTEXT_AWARE_WARNINGS=1` and a private disk-backed `TMPDIR`.

Run `python probe.py timing` in six fresh B/C processes, separately six C/B,
then six C/B with `taskset -c 2`. Run memory/profile modes separately. Setup:
six fresh B/C processes running `python setup.py`, kept beside `probe.py`.

### `probe.py`

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
                        first = rows[0] if shape == "explicit" else rows[0][0]
                        last = rows[-1] if shape == "explicit" else rows[-1][0]
                        assert (first.id, first.email, first.payload) == (
                            1,
                            "user1@example.com",
                            "x" * 32,
                        )
                        assert (last.id, last.email, last.payload) == (
                            width,
                            f"user{width}@example.com",
                            "x" * 32,
                        )
                        if shape != "explicit":
                            present = max(1, width // 2) if shape == "left" else width
                            assert sum(b is not None for a, b in rows) == present
                            other = rows[present - 1][1]
                            assert (other.id, other.email, other.payload) == (
                                present,
                                f"user{present}@example.com",
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


if __name__ == "__main__":
    asyncio.run(main())
```

### `setup.py` — diagnostic internal plan retention

```python
import gc, json, os, subprocess, sys, time, tracemalloc

sys.path.insert(0, os.getcwd())
from probe import query
from snekql._query_codec import DialectQueryCodec

codec = DialectQueryCodec.for_backend("sqlite")
samples = []
for shape in ("physical", "joined", "left", "explicit"):
    q = query(1000, shape)

    def compile_plan():
        return codec.compile_select_plan(q, cardinality="many")

    for _ in range(100):
        compile_plan()
    for trial in range(3):
        start = time.perf_counter()
        for _ in range(1000):
            compile_plan()
        elapsed = time.perf_counter() - start
        gc.collect()
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        retained = [compile_plan() for _ in range(200)]
        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples.append(
            dict(
                shape=shape,
                trial=trial + 1,
                operations=1000,
                seconds=elapsed,
                ops_s=1000 / elapsed,
                retained_plans=200,
                retained_bytes=current - before,
                peak_bytes=peak - before,
            )
        )
        del retained
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
```
