# Buffered SQLite worker dispatch — #496

Measured 2026-10-22 against merged `7259771`. The local aiosqlite adapter combines
ordinary buffered many-row SELECT execution, fetching and explicit cursor cleanup
into one worker submission. This is a snekql execution measurement, not the
original driver-only 2.81× feasibility result.

## Implementation and compatibility

`sqlite/_buffered_connection.py` isolates the private aiosqlite worker callback
`_execute_fetchall`, native `_conn` access, and construction of a locally owned
Connection subclass. Cursor cleanup runs in `finally` on the worker, including
fetch failure and caller cancellation. There is no global monkey-patch, installed
package modification, driver replacement, or dependency/version-bound change.

**Only reviewed aiosqlite 0.22.1 uses the subclass.** Unreviewed versions use the
ordinary driver connection and explicit asynchronous cursor lifecycle. Review the
callback/constructor contract and run `tests/sqlite/test_buffered_read_cleanup.py`
as well as lifecycle/error/telemetry coverage before extending that allowlist.
A missing or changed private hook must not silently opt an unknown release into
the optimization.

The neutral runtime recognizes an optional adapter capability, inside its
existing operation deadline and error/telemetry wrapper. It does not import a
backend or inspect concrete backend classes. Adapters without the capability
retain the existing path. Raw SQL, bounded cardinality, streaming and writes
(including RETURNING) keep their cursor lifecycle. Ordinary selects alone return
the unused SELECT rowcount sentinel; writes' rowcounts are not changed.

The SQLite adapter also falls back for ordinary, non-subclass driver connections.
Execution-time constraint failures are tagged separately from fetching/cleanup:
only the former retain existing savepoint recovery eligibility. Late failures
must fail closed. Explicit native exception causes are preserved under the
opt-in values diagnostics policy.

## Final-version comparative point reads

Final source `090e2ea` versus baseline, B/C/B then C/B/C, six rotating adapter
trials per process: **18 samples per adapter/revision**. Private disk-backed
SQLite, 2,000 seeded rows, 2,000 operations/trial, 200 warmups. This series follows
the wide-read probe in each process phase, with its database already closed;
the comparative driver runs in a separate child process, never concurrently.

| Adapter | Baseline ops/s | Candidate ops/s | Ratio | Median trial p99 ms, B → C |
| --- | ---: | ---: | ---: | ---: |
| raw | 12,346 | 13,372 | 1.083× | 0.177 → 0.168 |
| snekql | 2,867 | 3,037 | 1.060× | 0.646 → 0.592 |
| SQLAlchemy | 3,045 | 3,024 | 0.993× | 0.654 → 0.654 |

The snekql throughput median improves **6%**, but the raw control also improves
8%. These observations do not isolate a universal 6% causal gain or guarantee a
latency improvement. No ratios are adjusted by controls or multiplied by earlier
construction/protocol results.

## Diagnostic matrix and repeat

The initial clean implementation `6929479` was measured before the exception-chain
fix and unknown-version setup fallback. Neither refinement changes the successful
buffered-read callback on 0.22.1. The initial series remains separately labeled;
the final comparative, wide and follow-up series use final production code.

Six alternating processes, six 2,000-read trials/case after 200 warmups. Every read
checks its row. Shared transactions amortize lifecycle work and are not substitutes
for per-read transaction semantics.

| Output / query / transaction | Baseline ops/s | Candidate ops/s | Ratio |
| --- | ---: | ---: | ---: |
| Projection / prebuilt / shared | 8,957 | 12,317 | 1.375× |
| Projection / prebuilt / per-read | 4,003 | 4,387 | 1.096× |
| Projection / rebuilt / shared | 6,177 | 5,624 | 0.910× |
| Projection / rebuilt / per-read | 2,910 | 3,479 | 1.195× |
| Model / prebuilt / shared | 10,049 | 12,418 | 1.236× |
| Model / prebuilt / per-read | 3,966 | 4,523 | 1.141× |
| Model / rebuilt / shared | 8,437 | 11,352 | 1.346× |
| Model / rebuilt / per-read | 3,677 | 4,176 | 1.136× |

The unfavorable projection/rebuilt/shared case triggered a longer final-version
repeat: three processes/revision, ten 5,000-read trials/process after 1,000 warmups,
alternating raw/snekql order within each process. Snekql **5,568 → 6,205 ops/s
(1.114×)**, raw **28,260 → 29,171 (1.032×)**. The original 9% decrease did not
reproduce; its samples remain published rather than replaced by the follow-up.
Raw validates equivalent field values but does not reproduce the entire snekql
builder/model contract; it is a driver control, not an absolute ORM comparison.

The initial comparative driver also measured both backends, with alternating
backend order. SQLite snekql **2,996 → 3,221 ops/s (1.075×)**; raw **13,635 →
14,062**, SQLAlchemy **3,209 → 3,285**. MariaDB is a fallback-path control: snekql
**2,699 → 2,675 (0.991×)**, raw **12,854 → 12,747**, SQLAlchemy **3,201 → 3,238**.
No MariaDB gain is claimed.

## Wide reads and memory

Final-version wide reads retain the prebuilt/shared-transaction contract, selecting
1,000 of 2,000 seeded rows. Six processes, six trials/case/process, 100 reads/trial,
10 warmups. Count and endpoint field values are checked on every read.

| Output | Baseline reads/s | Candidate reads/s | Ratio |
| --- | ---: | ---: | ---: |
| Whole model | 270 | 281 | 1.04× |
| Named projection | 301 | 307 | 1.02× |

The advantage is smaller when row materialization dominates. These are observations,
not a bulk-throughput promise.

Separate tracemalloc runs retain 20 reads × 1,000 rows, three samples/case/revision:

| Output | Retained bytes, B → C | Peak traced bytes, B → C |
| --- | ---: | ---: |
| Model | 6,356,069 → 6,365,570 | 6,455,219 → 6,455,138 |
| Projection | 12,756,005 → 12,765,538 | 12,841,555 → 12,841,410 |

Retention is approximately unchanged (under 0.2% difference), not reduced. These
snapshots exclude import/connection setup and native allocations, and are not RSS.

## Mechanism and validation

Separate initial-implementation profiles of 2,000 prebuilt shared-transaction
projection reads show worker-queue gets **6,003 → 2,003**, thread-safe wakeups
**6,004 → 2,004**, and event-loop iterations **14,014 → 6,014**. This supports the
round-trip mechanism; instrumented wall time is not used as speedup evidence.

Eight public-interface safety cases pass on baseline and candidate. Native cursor
factories inject system-boundary failures, not private snekql mocks or call-count
assertions. Unsafe skipped cleanup, premature capacity release, omitted cleanup
on fetch failure, recoverable late constraints, dropped native causes, and use of
an unreviewed combined helper are caught. All deliberate mutations are reverted.

Existing external-driver fault injection was extended to both public driver entry
points so buffered error-classification/redaction assertions still exercise the
failure rather than silently bypassing the injection. The assertions were not
weakened. Focused medium SQLite/runtime coverage passed 735 cases before the final
two safety additions; all eight final safety cases pass independently. An initial
full run passed 3,949 cases; the final full run and CI results are recorded in the PR.

## Evidence, exclusions and reproduction

[Initial manifest](results/sqlite-buffered-496/manifest.json) and
[216 comparative trials](results/sqlite-buffered-496/trials.csv);
[final manifest](results/sqlite-buffered-496/final-manifest.json) and
[108 final comparative trials](results/sqlite-buffered-496/final-trials.csv).
[Probe metadata](results/sqlite-buffered-496/probe-manifest.json) joins:
[288 execution trials](results/sqlite-buffered-496/execution-trials.csv),
[72 wide-read trials](results/sqlite-buffered-496/wide-trials.csv),
[120 follow-up trials](results/sqlite-buffered-496/followup-trials.csv), and
[12 memory samples](results/sqlite-buffered-496/memory-trials.csv).

All retained timing processes exited zero with clean source trees and empty stderr.
Timing, memory, profiles and owned tests are sequential. An initial wide probe
incorrectly assumed seeded IDs began at zero; its assertion failed before retained
wide measurements, and that preflight is excluded. The seed begins at one.

Same host as #495: CPython 3.15.0, aiosqlite 0.22.1, SQLite 3.53.1, MariaDB 13.0.2,
Pydantic 2.14.0, anyio 4.15.1, SQLAlchemy 2.1.1, aiomysql 0.3.2; i7-14700F,
28 logical CPUs, powersave, no CPU pinning or exclusive host ownership. Private
Btrfs disk-backed databases; SQLite WAL/NORMAL, MariaDB redo flush policy 1 and
binary logging off. Runners wait for visible Python tests before commands, but
other sessions can still start during a command.

Raw logs/profiles remain under `/home/crpier/.cache/snekql-496/`. Set a private
disk-backed `TMPDIR` and `PYTHON_CONTEXT_AWARE_WARNINGS=1`, use identical dependencies,
and run the probes below from each exact worktree, saving scripts outside source
roots. The comparative command is `python -m benchmarks.compare --backend sqlite
--workload point-read --rows 2000 --operations 2000 --trials 6 --warmup 200`;
use `mariadb` for that control. No package version/lockfile was changed.

### Diagnostic execution: `python execution.py sqlite timing PREFIX`

Use `profile` separately to write one profile per case.

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

### Wide reads and final comparative series: `python wide.py timing`

Use `memory` separately; that mode does not launch the comparative driver.

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
```

### Longer repeat: `python followup.py PHASE_INDEX`

Use phase indices 0–5 to alternate initial adapter order.

```python
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
            query = sqlite.select(BenchUser).where(BenchUser.id.eq(42))

            async def snekql_read():
                rows = await tx.fetch_all(
                    sqlite.select(BenchUser)
                    .project(
                        Record,
                        id=BenchUser.id,
                        email=BenchUser.email,
                        payload=BenchUser.payload,
                    )
                    .where(BenchUser.id.eq(42))
                )
                assert len(rows) == 1
                row = rows[0]
                assert (row.id, row.email, row.payload) == (
                    42,
                    "user42@example.com",
                    "x" * 32,
                )

            async def raw_read():
                async with raw.execute(
                    "SELECT id, email, payload FROM bench_user WHERE id = ?", (42,)
                ) as cursor:
                    rows = await cursor.fetchall()
                assert len(rows) == 1
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
