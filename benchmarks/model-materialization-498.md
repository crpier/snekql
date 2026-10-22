# Ordered model-row materialization — #498

Measured 2026-10-22: merged baseline `5645557` (including #497) versus clean
implementation `3def82e`. This is an incremental comparison, not a product of
previous performance ratios.

## Change and semantic constraints

A physical source already resolves its ordered columns when building its source
shape. Whole-model decoding nevertheless created a name/value dictionary, copied
it, and resolved the model's columns again for every row.

`SourceRowShape` now retains the resolved frozen column mapping. Its positional
decoder avoids those per-row dictionaries and repeated metadata lookup. Every
column decode and ordinary attribute/descriptor assignment remains. Aliases still
produce the original model and use its columns; a differing alias column order
retains the general name-based path. CTE named results and LEFT JOIN presence
handling are unchanged. The general mapping decoder remains for other callers,
including whole-model RETURNING.

No global cache, direct instance-storage shortcut, validation bypass, backend
import, dependency change or runtime lifecycle change is introduced. Setup retains
one additional mapping reference per source shape, rather than adding state to
each returned row or column. The mapping is the existing frozen metadata, not a
new mutable copy. Per-execution validation and live descriptor decoding/assignment
remain observable.

## Wide reads: the targeted workload

Private disk-backed SQLite with 2,000 seeded rows. Each read selects 1,000 ordered
rows, checking count and endpoint field values. Prebuilt queries share a transaction.
Six fresh processes B/C/B then C/B/C; six trials of 100 reads after 10 warmups per
case/process: **18 samples per case/revision**.

| Output | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Whole model | 285 | 343 | **1.206×** |
| Named projection control | 307 | 307 | 1.003× |

The whole-model median improves about **21%**, with the unaffected projection
control approximately flat. This does not establish a gain for MariaDB or every
result shape; real-database tests cover both backends, but timing here is SQLite.

## Single-row controls and follow-up

After each wide probe has closed its database, a separate comparative process
runs point reads: 2,000 rows, 2,000 operations/trial, 200 warmups, six rotating
adapter trials. Each table entry pools 18 samples/revision. This comparative
contract uses named projections, not the newly optimized whole-model decoder.

| Adapter | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| raw | 13,834 | 12,984 | 0.939× |
| snekql | 3,081 | 2,904 | 0.943× |
| SQLAlchemy | 3,088 | 2,896 | 0.938× |

All three decrease similarly. These controls do not establish an attributable
point-read regression or gain; results are not normalized by control ratios.

A separate eight-case diagnostic uses six 2,000-read trials after 200 warmups in
each of the six processes. Every operation checks its returned row. Transaction
policies below are deliberately different workloads, not interchangeable semantics.

| Output / query / transaction | Baseline ops/s | Candidate ops/s |
| --- | ---: | ---: |
| Model / prebuilt / shared | 13,219 | 10,385 |
| Model / prebuilt / per-read | 4,003 | 4,058 |
| Model / rebuilt / shared | 9,300 | 10,326 |
| Model / rebuilt / per-read | 4,114 | 3,620 |
| Projection / prebuilt / shared | 11,153 | 9,647 |
| Projection / prebuilt / per-read | 4,164 | 3,923 |
| Projection / rebuilt / shared | 6,013 | 6,841 |
| Projection / rebuilt / per-read | 3,049 | 3,091 |

The unfavorable model/prebuilt/shared and model/rebuilt/per-read cases prompted
longer repeats with raw controls. Each case runs six fresh alternating processes,
ten trials of 5,000 reads after 1,000 warmups, alternating raw/snekql order within
each process: 30 samples per adapter/revision/case.

| Repeat | Adapter | Baseline ops/s | Candidate ops/s | Ratio |
| --- | --- | ---: | ---: | ---: |
| Model / prebuilt / shared | snekql | 10,939 | 10,874 | 0.994× |
| Model / prebuilt / shared | raw | 27,455 | 27,202 | 0.991× |
| Model / rebuilt / per-read | snekql | 3,659 | 3,886 | 1.062× |
| Model / rebuilt / per-read | raw | 14,122 | 15,128 | 1.071× |

The large decreases did not reproduce. The per-read increase also moves with the
raw control, so **no single-row execution improvement is claimed**. Original
unfavorable data remain published; repeats supplement rather than replace them.
Raw validates equivalent field values but does not reproduce the full model/builder
contract. It is a driver control, not an absolute ORM comparison.

## Memory and profiles

Separate tracemalloc runs retain 20 reads × 1,000 rows, three samples/case/revision:

| Output | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Whole model | 6,365,570 → 6,365,506 | 6,455,138 → 6,443,034 |
| Projection | 12,765,538 → 12,765,538 | 12,841,410 → 12,841,410 |

Returned-row retention is unchanged. This is not a total-RSS, setup-memory or
allocation-rate measurement; a source shape now carries an extra mapping reference.

Separate profiles consume 100 × 1,000 rows per shape/revision. For whole models:

- `require_model_columns`: **100,500 → 500** calls.
- Row decoder: 100,000 calls in both versions; cumulative instrumented time
  **1.138 → 0.922 seconds**.
- **300,000 `Attr.decode`, 300,000 model `__setattr__` and 300,000 descriptor
  `__set__` calls remain** in both profiles.

Counts corroborate the avoided work and preserved dispatch. Profiling perturbs
costs; the throughput claim comes from the separate unprofiled wide-read trials.

## Validation and evidence

Six public execution cases pass on baseline and candidate: buffered/streamed
reads, original/aliased models, descriptor transforms, immutable returned rows,
and changing validation policy while reusing a query. Unsafe direct-storage writes,
wrong alias model construction and validation bypasses fail these regressions;
all mutations are reverted. Alias/join/nullable-presence focused coverage passed
34 cases; medium SQLite/runtime coverage passed 743 cases. Full local suite:
**3,957 passed**, exit 0, 948.83s. Static and CI status is recorded in the PR.

[Probe metadata](results/model-materialization-498/probe-manifest.json) joins
[72 wide trials](results/model-materialization-498/wide-trials.csv),
[288 execution diagnostics](results/model-materialization-498/execution-trials.csv),
[240 follow-up trials](results/model-materialization-498/followup-trials.csv), and
[12 memory samples](results/model-materialization-498/memory-trials.csv).
[Comparative metadata](results/model-materialization-498/final-manifest.json) and
[108 comparative trials](results/model-materialization-498/final-trials.csv)
retain commands, revisions, interpreter, session policies and host details.
Follow-up run suffixes distinguish `shared` and `per_read` cases.

All retained timing processes exited zero with clean source trees. No retained
measurements overlap owned validation runs. Timing, memory and profile commands
run sequentially. Profiles are written after memory tracing stops and its database
closes. The diagnostic profile preceding implementation is separate evidence,
not a candidate comparison. No speed or private-call-count assertions enter CI.

CPython 3.15.0, SQLite 3.53.1, aiosqlite 0.22.1, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1; i7-14700F, 28 logical CPUs, powersave, no pinning or exclusive
host control. Private Btrfs disk-backed databases, SQLite WAL/NORMAL. Runners wait
for visible Python tests, but other sessions can start work during a command.
Raw scripts, reports and profiles remain in `/home/crpier/.cache/snekql-498/`.

## Reproduction

Use identical dependencies, private disk-backed `TMPDIR` and
`PYTHON_CONTEXT_AWARE_WARNINGS=1`. Save scripts outside source roots and run from
the exact worktrees above. The comparative command is `python -m benchmarks.compare
--backend sqlite --workload point-read --rows 2000 --operations 2000 --trials 6
--warmup 200`.

### Wide reads: `python wide.py timing` or `python wide.py memory`

The timing mode also launches the comparative command, after closing the wide-read
database. Memory mode invokes the separate profile script printed below.

```python
import asyncio, gc, json, os, subprocess, sys, tempfile, time, tracemalloc
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_sqlite import seed
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "wide.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
        ):
            for shape in ("model", "projection"):
                q = (
                    sqlite.select(BenchUser)
                    .where(BenchUser.id.lte(1000))
                    .order_by(BenchUser.id.asc())
                )
                if shape == "projection":
                    q = q.project(
                        Record,
                        id=BenchUser.id,
                        email=BenchUser.email,
                        payload=BenchUser.payload,
                    )

                async def read():
                    rows = await tx.fetch_all(q)
                    assert len(rows) == 1000
                    assert (rows[0].id, rows[0].email, rows[0].payload) == (
                        1,
                        "user1@example.com",
                        "x" * 32,
                    )
                    assert (rows[-1].id, rows[-1].email, rows[-1].payload) == (
                        1000,
                        "user1000@example.com",
                        "x" * 32,
                    )
                    return rows

                for _ in range(10):
                    await read()
                for trial in range(6 if sys.argv[1] == "timing" else 3):
                    if sys.argv[1] == "timing":
                        start = time.perf_counter()
                        for _ in range(100):
                            await read()
                        elapsed = time.perf_counter() - start
                        samples.append(
                            dict(
                                shape=shape,
                                trial=trial + 1,
                                operations=100,
                                rows_per_operation=1000,
                                seconds=elapsed,
                                ops_s=100 / elapsed,
                            )
                        )
                    else:
                        gc.collect()
                        tracemalloc.start()
                        before = tracemalloc.get_traced_memory()[0]
                        retained = [await read() for _ in range(20)]
                        gc.collect()
                        current, peak = tracemalloc.get_traced_memory()
                        tracemalloc.stop()
                        samples.append(
                            dict(
                                shape=shape,
                                trial=trial + 1,
                                retained_rows=20000,
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
                mode=sys.argv[1],
                samples=samples,
            )
        )
    )


asyncio.run(main())
# After the wide probe has closed its database, measure the final source's
# comparative point-read contract in a separate process. Never overlap probes.
if sys.argv[1] == "timing":
    target = Path(__file__).parent / f"final-point-{time.time_ns()}.json"
    command = [
        sys.executable,
        "-m",
        "benchmarks.compare",
        "--backend",
        "sqlite",
        "--workload",
        "point-read",
        "--rows",
        "2000",
        "--operations",
        "2000",
        "--trials",
        "6",
        "--warmup",
        "200",
    ]
    start = time.time()
    with target.open("w") as output:
        result = subprocess.run(
            command, stdout=output, stderr=subprocess.PIPE, text=True
        )
    target.with_suffix(".command.json").write_text(
        json.dumps(
            dict(
                command=command,
                cwd=os.getcwd(),
                exit=result.returncode,
                stderr=result.stderr,
                started=start,
                elapsed=time.time() - start,
            )
        )
    )
    if result.returncode:
        raise RuntimeError(result.stderr)

if sys.argv[1] == "memory":
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    with (Path(__file__).parent / f"profile-{commit}.json").open("w") as output:
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "profile.py"), "profile"],
            stdout=output,
            check=True,
        )
```

### Profiles: `python profile.py profile`

```python
import asyncio, gc, json, os, subprocess, sys, tempfile, time, tracemalloc, cProfile
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_sqlite import seed
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "wide.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() as tx,
        ):
            for shape in ("model", "projection"):
                q = (
                    sqlite.select(BenchUser)
                    .where(BenchUser.id.lte(1000))
                    .order_by(BenchUser.id.asc())
                )
                if shape == "projection":
                    q = q.project(
                        Record,
                        id=BenchUser.id,
                        email=BenchUser.email,
                        payload=BenchUser.payload,
                    )

                async def read():
                    rows = await tx.fetch_all(q)
                    assert len(rows) == 1000
                    assert (rows[0].id, rows[0].email, rows[0].payload) == (
                        1,
                        "user1@example.com",
                        "x" * 32,
                    )
                    assert (rows[-1].id, rows[-1].email, rows[-1].payload) == (
                        1000,
                        "user1000@example.com",
                        "x" * 32,
                    )
                    return rows

                for _ in range(10):
                    await read()
                profile = cProfile.Profile()
                profile.enable()
                for _ in range(100):
                    await read()
                profile.disable()
                profile.dump_stats(
                    str(
                        Path(__file__).parent
                        / f"{subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()}-{shape}.prof"
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
                mode=sys.argv[1],
                samples=samples,
            )
        )
    )


asyncio.run(main())
```

### Diagnostic execution: `python execution.py sqlite timing PREFIX`

```python
import asyncio
import cProfile
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_contract import Record
from snekql import sqlite, mariadb
from snekql.testing.mariadb import temporary_mariadb_server

backend, mode, output = sys.argv[1:]


@asynccontextmanager
async def database():
    if backend == "sqlite":
        from benchmarks._comparison_sqlite import seed
        from benchmarks._models_sqlite import BenchUser

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.db"
            await seed(path, 2000)
            async with await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db:
                yield sqlite, BenchUser, db
    else:
        from benchmarks._comparison_mariadb import seed
        from benchmarks._models_mariadb import BenchUser

        async with temporary_mariadb_server(transports={"tcp"}) as server:
            config = server.config(pool_size=1)
            await seed(config, 2000)
            async with await mariadb.Database.initialize(config) as db:
                yield mariadb, BenchUser, db


async def main():
    rows = []
    async with database() as (api, model, db):
        for shape in ("projection", "model"):

            def build():
                query = api.select(model)
                if shape == "projection":
                    query = query.project(
                        Record, id=model.id, email=model.email, payload=model.payload
                    )
                return query.where(model.id.eq(42))

            prebuilt = build()
            for rebuild in (False, True):
                for reuse in (True, False):
                    label = f"{shape}-{'rebuild' if rebuild else 'prebuilt'}-{'shared_tx' if reuse else 'per_tx'}"

                    async def one(tx):
                        result = await tx.fetch_all(build() if rebuild else prebuilt)
                        assert len(result) == 1
                        row = result[0]
                        assert (row.id, row.email, row.payload) == (
                            42,
                            "user42@example.com",
                            "x" * 32,
                        )

                    async def run(count):
                        if reuse:
                            async with db.transaction() as tx:
                                for _ in range(count):
                                    await one(tx)
                        else:
                            for _ in range(count):
                                async with db.transaction() as tx:
                                    await one(tx)

                    await run(200)
                    if mode == "profile":
                        profile = cProfile.Profile()
                        profile.enable()
                        await run(2000)
                        profile.disable()
                        profile.dump_stats(f"{output}-{label}.prof")
                    else:
                        for trial in range(6):
                            start = time.perf_counter()
                            await run(2000)
                            elapsed = time.perf_counter() - start
                            rows.append(
                                dict(
                                    label=label,
                                    trial=trial + 1,
                                    operations=2000,
                                    seconds=elapsed,
                                    ops_s=2000 / elapsed,
                                )
                            )
    print(
        json.dumps(
            dict(
                backend=backend,
                mode=mode,
                commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                dirty=bool(
                    subprocess.check_output(["git", "status", "--porcelain"], text=True)
                ),
                samples=rows,
            )
        )
    )


asyncio.run(main())
```

### Repeat: `python followup.py PHASE_INDEX shared` or `per_read`

Phase indices 0–5 alternate initial adapter order.

```python
from contextlib import nullcontext
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from aiosqlite import connect
from benchmarks._comparison_sqlite import seed
from benchmarks._comparison_contract import Record
from benchmarks._models_sqlite import BenchUser
from snekql import sqlite

case = sys.argv[2]


async def main():
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "followup.db"
        await seed(path, 2000)
        async with (
            await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal")
            ) as db,
            db.transaction() if case == "shared" else nullcontext() as tx,
            connect(path, isolation_level=None) as raw,
        ):
            for sql in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA foreign_keys=ON",
                "PRAGMA busy_timeout=5000",
            ) + (("BEGIN",) if case == "shared" else ()):
                async with raw.execute(sql):
                    pass
            query = sqlite.select(BenchUser).where(BenchUser.id.eq(42))

            async def snekql_read():
                if case == "shared":
                    rows = await tx.fetch_all(query)
                else:
                    async with db.transaction() as single:
                        rows = await single.fetch_all(
                            sqlite.select(BenchUser).where(BenchUser.id.eq(42))
                        )
                assert len(rows) == 1
                row = rows[0]
                assert (row.id, row.email, row.payload) == (
                    42,
                    "user42@example.com",
                    "x" * 32,
                )

            async def raw_read():
                if case != "shared":
                    async with raw.execute("BEGIN"):
                        pass
                async with raw.execute(
                    "SELECT id, email, payload FROM bench_user WHERE id = ?", (42,)
                ) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
                if case != "shared":
                    await raw.commit()
                row = Record.model_validate(
                    dict(zip(("id", "email", "payload"), rows[0], strict=True)),
                    strict=True,
                )
                assert (row.id, row.email, row.payload) == (
                    42,
                    "user42@example.com",
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
