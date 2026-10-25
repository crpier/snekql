# Current runtime reassessment — #534

Measured **2026-10-25**, clean main **`395f731c58916109a21b606777fb1729543e92a8`**
(merged #533). This is a **current baseline and prioritization investigation**,
not an implementation or before/after speedup claim.

## Executive decision

**Stop opportunistic materialization micro-optimizations. No new high-confidence,
large, semantics-preserving runtime win was established.**

1. **Use existing immutable builder reuse where application semantics allow.**
   Reusing a projection stem while supplying a new predicate can save repeated
   construction without a new interface. A focused experiment below shows useful
   results, but also one adverse MariaDB per-operation process.
2. **Transaction scope has major leverage, but is an application policy decision.**
   Shared versus per-operation transactions are not interchangeable guarantees.
   Do not remove BEGIN/COMMIT, admission, deadlines or cancellation-safe cleanup.
3. **Prepared execution is a conditional design question, not the next optimization.**
   Warm full-plan construction costs ~24–32 µs on these narrow queries, including
   SQL compilation. It is not hundreds of microseconds of free headroom. Consider
   a design only for demonstrated, high-volume repeated query shapes.
4. **Bulk encoding is visible, not an established large avoidable cost.** SQLite
   spends time in input-model construction, native encoding and verified readback;
   MariaDB's durable commit dominates this diagnostic. No batching/codec rewrite
   proposed from these observations.

There is no runtime change, cache, prepared-query interface, dependency change,
or permission to weaken validation/ownership/error semantics in this PR.

## Primary comparative workloads

The existing `python -m benchmarks.compare` command: six fresh processes per
backend/case, six rotating adapter trials each, **36 samples/adapter/case**.
Backend order alternates each outer round; case order rotates. Rows are the same
integer ID/email/32-byte payload fixture; all returned values/counts are checked.

| Case | Rows | Operations/trial | Warmup | Workers / capacity | Batch |
| --- | ---: | ---: | ---: | --- | ---: |
| Point | 2,000 | 2,000 | 200 | 1 / 1 | one row |
| Join | 2,000 | 2,000 | 200 | 1 / 1 | one related row |
| Stream | 20,000 | 5 scans | 1 | 1 / 1 | 256 |
| Bulk | separate write table | 100 batches | 10 | 1 / 1 | 64 |
| Contention | 2,000 | 2,000 total | 200 | 8 / 1 | one row |

Each primary operation explicitly begins and acknowledges COMMIT; bulk commits
an INSERT and then separately reads back/validates/commits the inserted range.
This is **verified bulk throughput**, not INSERT-only timing. Models/input/query
construction and checks are included. Stream consumption stays bounded and
checks every identity in order. [Full contract](comparison.md).

Medians below; bracketed values are the full range of trial throughput. p99 is
the median of trial p99 values; loop delay is the median trial maximum heartbeat
lateness. Short scan trials give sparse heartbeat samples, not precise tails.

| Backend / case | Adapter | Ops/s [range] | p99 ms | Loop delay ms |
| --- | --- | ---: | ---: | ---: |
| sqlite / point | raw | 10,333.29 [6,776.92–14,832.51] | 0.222 | 0.049 |
| sqlite / point | snekql | 2,528.42 [1,767.22–3,421.24] | 0.667 | 0.210 |
| sqlite / point | sqlalchemy | 2,352.97 [1,498.30–3,459.15] | 0.759 | 0.187 |
| sqlite / contention | raw | 8,770.23 [4,744.62–13,067.89] | 1.685 | 0.055 |
| sqlite / contention | snekql | 1,806.83 [948.82–2,743.40] | 6.193 | 0.378 |
| sqlite / contention | sqlalchemy | 2,135.01 [928.16–2,948.35] | 5.826 | 0.208 |
| sqlite / join | raw | 10,655.96 [6,262.35–13,915.40] | 0.206 | 0.043 |
| sqlite / join | snekql | 2,224.33 [1,429.68–2,919.93] | 0.766 | 0.231 |
| sqlite / join | sqlalchemy | 2,235.73 [1,365.74–2,925.16] | 0.800 | 0.199 |
| sqlite / stream | raw | 30.72 [16.93–40.87] | 42.208 | 0.626 |
| sqlite / stream | snekql | 12.79 [7.34–16.10] | 93.439 | 1.564 |
| sqlite / stream | sqlalchemy | 15.33 [8.48–20.41] | 88.578 | 1.432 |
| sqlite / bulk | raw | 2,335.09 [1,559.29–3,456.75] | 0.722 | 0.117 |
| sqlite / bulk | snekql | 530.88 [370.41–753.89] | 2.891 | 0.646 |
| sqlite / bulk | sqlalchemy | 391.28 [294.02–548.31] | 3.748 | 1.501 |
| mariadb / point | raw | 10,171.40 [6,950.52–13,032.68] | 0.239 | 0.091 |
| mariadb / point | snekql | 2,249.66 [1,606.85–2,699.93] | 0.853 | 0.289 |
| mariadb / point | sqlalchemy | 2,702.96 [1,763.89–3,207.44] | 0.760 | 0.264 |
| mariadb / contention | raw | 9,828.20 [5,307.30–12,395.69] | 1.723 | 0.102 |
| mariadb / contention | snekql | 2,076.17 [1,130.07–2,376.67] | 6.580 | 0.434 |
| mariadb / contention | sqlalchemy | 2,688.06 [1,420.13–3,252.64] | 5.226 | 0.316 |
| mariadb / join | raw | 9,175.20 [5,220.33–12,100.96] | 0.253 | 0.115 |
| mariadb / join | snekql | 1,922.92 [1,160.04–2,392.10] | 0.957 | 0.388 |
| mariadb / join | sqlalchemy | 2,397.18 [1,325.77–2,965.32] | 0.830 | 0.328 |
| mariadb / stream | raw | 20.75 [13.86–21.81] | 49.948 | 2.033 |
| mariadb / stream | snekql | 11.50 [8.22–12.03] | 88.855 | 3.616 |
| mariadb / stream | sqlalchemy | 13.91 [8.77–14.38] | 72.479 | 2.885 |
| mariadb / bulk | raw | 160.74 [100.53–178.23] | 7.112 | 1.062 |
| mariadb / bulk | snekql | 132.70 [97.79–144.83] | 9.973 | 1.076 |
| mariadb / bulk | sqlalchemy | 129.63 [93.62–137.87] | 9.696 | 1.736 |

Ranges are large and controls move substantially. Raw is not snekql with zero
avoidable overhead: its input/lifecycle interface and safety responsibilities
are different. The gap is **not an achievable speedup budget**. SQLAlchemy Core
is sometimes faster and sometimes slower here; no universal ranking is claimed.
Do not compare these absolute values as a regression or cumulative gain against
September/earlier reports with different source, OS, dependencies or host state.

## Fixed-cost matrix: rebuild/reuse and transaction scope

Separate snekql-only processes, identical fixed identity 42 and checked result.
Named projection versus whole model, fully rebuilt versus prebuilt query, shared
versus per-operation transaction. Six processes/backend × six trials/case:
**36 samples/case**, 2,000 reads/trial after 200 warmups. Case order rotates and
reverses across processes. CPU is main-thread `thread_time`, not total/worker CPU.
A prebuilt query still receives a newly compiled execution plan on each fetch.

| Backend | Output | Query | Transaction | Ops/s | Main-thread µs/read |
| --- | --- | --- | --- | ---: | ---: |
| mariadb | model | prebuilt | per operation | 3,545.81 | 266.10 |
| mariadb | model | prebuilt | shared | 7,591.99 | 121.33 |
| mariadb | model | rebuilt | per operation | 3,333.01 | 284.71 |
| mariadb | model | rebuilt | shared | 6,446.27 | 143.22 |
| mariadb | named | prebuilt | per operation | 3,453.66 | 273.82 |
| mariadb | named | prebuilt | shared | 6,952.89 | 131.82 |
| mariadb | named | rebuilt | per operation | 2,746.63 | 347.08 |
| mariadb | named | rebuilt | shared | 4,739.29 | 197.96 |
| sqlite | model | prebuilt | per operation | 4,494.39 | 202.15 |
| sqlite | model | prebuilt | shared | 12,920.56 | 71.92 |
| sqlite | model | rebuilt | per operation | 4,076.20 | 224.26 |
| sqlite | model | rebuilt | shared | 11,119.00 | 83.13 |
| sqlite | named | prebuilt | per operation | 4,239.82 | 214.44 |
| sqlite | named | prebuilt | shared | 11,871.11 | 78.86 |
| sqlite | named | rebuilt | per operation | 3,203.02 | 289.97 |
| sqlite | named | rebuilt | shared | 6,670.92 | 143.06 |

The shared transaction includes its entry/commit once per trial, not once per
read. That changes atomicity, snapshot/lock duration, rollback scope and pool
occupancy. It is **not** a runtime patch or evidence to silently coalesce requests.
Fixed identity/query reuse also differs from the comparative cycling-identity
workload; do not normalize or pool their throughput.

### Existing projection-stem reuse, fresh identity each operation

Follow-up using only the current public builder interface. Three fresh processes
per backend, six rotating trials of four cases: rebuild whole named query versus
reuse its projection stem, crossed with the two transaction scopes. Each trial
cycles all 2,000 identities, validates every result, 200 warmups/2,000 operations.
**18 samples/case**, nested in only three independent processes—not 18 independent
host conditions. Both construction styles still compile a fresh plan per fetch.

| Backend | Transaction | Full rebuild ops/s | Stem reuse ops/s | Main-thread µs/read full → stem |
| --- | --- | ---: | ---: | ---: |
| SQLite | Per operation | 2,977.80 | 3,788.82 | 311.22 → 239.77 |
| SQLite | Shared | 5,599.41 | 9,072.73 | 170.52 → 102.88 |
| MariaDB | Per operation | 2,688.06 | 3,219.19 | 353.81 → 292.40 |
| MariaDB | Shared | 4,575.73 | 6,155.47 | 203.07 → 148.14 |

Per-process ratios (stem/full medians), in execution order:

- SQLite per-operation: **1.169×, 1.123×, 1.264×**; shared: **2.134×, 1.403×, 1.475×**.
- MariaDB per-operation: **1.180×, 0.953×, 1.209×**; shared: **1.372×, 1.361×, 1.333×**.

The adverse MariaDB per-operation process remains; pooled median ratios need not
match process ratios. Useful application-level evidence, **not a guaranteed
percentage improvement**. Example pattern with application-defined models:

```python
projection = sqlite.select(User).project(
    UserResult, id=User.id, email=User.email, payload=User.payload
)


async def find_user(transaction, identity):
    query = projection.where(User.id.eq(identity))
    return await transaction.fetch_all(query)
```

The stem captures no connection/transaction; each immutable branch adds its own
predicate. Prebuild only once declarations are ready; deliberately moving query
construction to initialization can move construction errors there. This does not
cache a decoder, SQL plan, result, validation flag or live driver resource.

## Diagnostic phase accounting, separate from primary timing

Public observer plus explicit stage clocks; three processes/backend, three
trials each. Empty transaction / named point: 1,000 operations/trial; verified
64-row bulk: 50 batches/trial; ten warmups. These clocks and callbacks add overhead.
**Do not subtract from primary timings or interpret instrumented stage values as
uninstrumented latency.** Stage medians below need not sum to median totals.

| Diagnostic | SQLite µs/operation | MariaDB µs/operation |
| --- | ---: | ---: |
| Empty transaction, total wall | 153.83 | 133.35 |
| Empty transaction, entry / exit | 62.27 / 82.42 | 57.81 / 67.32 |
| Named point, total wall | 407.18 | 436.16 |
| Named point, query build | 64.17 | 61.18 |
| Named point, entry / exit | 82.50 / 106.16 | 76.61 / 93.70 |
| Named point, fetch (includes compilation) | 137.39 | 188.70 |
| Named point, materialization event | 11.91 | 11.65 |
| Bulk-64, total wall | 1,463.55 | 8,720.77 |
| Bulk-64, input Pending models | 181.34 | 193.67 |
| Bulk-64, INSERT query build | 15.92 | 16.77 |
| Bulk-64, write entry | 72.94 | 87.42 |
| Bulk-64, write execute (includes encoding) | 454.86 | 2,316.76 |
| Bulk-64, write exit (includes COMMIT) | 104.72 | **5,260.25** |
| Bulk-64, read query build | 88.78 | 118.51 |
| Bulk-64, read entry / exit | 72.05 / 96.12 | 103.75 / 118.70 |
| Bulk-64, read fetch | 331.46 | 604.76 |

Observer event durations are **nested, not additive**. Per-operation counts:
empty transaction two driver events; point three; verified bulk six and two
transaction/acquisition pairs. Driver/transaction totals include different scopes
than the outer stages. No SQL/bind values or exception objects collected by the
observer. All operations and decoded values passed correctness checks.

This supports examining fixed work rather than another per-value tweak. It does
**not** identify a removable transaction safety check. On MariaDB, commit-stage
wall time dominates this small durable batch workload; client CPU savings cannot
remove acknowledged durability. SQLite WAL/NORMAL is a different durability policy.

### Warm construction, SQL and full-plan setup

Separate unprofiled synchronous diagnostic: three processes/backend, six rotating
trials, 10,000 constructions/trial after 1,000 warmups. **18 samples/case**.
SQL/parameters agree and bind identity 42. Full-plan measurement invokes private
`DialectQueryCodec.compile_select_plan(..., cardinality="many")` **only as an
allocation/CPU diagnostic**, not a test seam, supported execution interface or
proposed public prepare operation. Public `.compile()` is SQL-only.

| Backend | Output | Builder µs | SQL-only µs | Full-plan µs |
| --- | --- | ---: | ---: | ---: |
| SQLite | Model | 5.94 | 20.31 | 23.98 |
| SQLite | Named | 32.19 | 21.93 | 30.32 |
| MariaDB | Model | 5.95 | 21.63 | 25.13 |
| MariaDB | Named | 32.85 | 23.18 | 31.62 |

**Full-plan includes SQL compilation; do not add those two columns.** These are
isolated warmed costs, not a measured prepared-execution speedup or a strict
end-to-end upper bound under different host conditions. For a new prepared
interface, retain per-execution validation, backend ownership and binding rules;
define descriptor/extension mutation, unresolved declarations, NULL ownership,
error timing and cache lifetime explicitly. No design or implementation supplied.

## Profiles: locate work, do not report their timings as throughput

Eighteen separate cProfiles: eight point cases × two backends, 2,000 reads/case,
and 200 verified bulk-64 operations/backend, all after warmup. Raw `.prof` files
remain in the cache; complete function counts/self/cumulative times are published
in `profile-functions.csv`. Coroutine call counts can include resumptions, not
logical database requests. Worker-thread CPU/native database time is not captured.

Bulk profiles contain 12,800 input model constructions, 12,800 row encodings and
38,400 field encodings per backend, plus complete readback/materialization. The
SQLite profile's cumulative `_compile_insert_sql` is 0.269 s, inside which
`_encode_insert_row` is 0.255 s; input population 0.177 s and read materialization
0.117 s. MariaDB respective cumulative values: 0.237 s / 0.224 s, input population
0.154 s and read materialization 0.098 s. **Nested cumulative values cannot be
summed; profiling overhead is substantial.** Encoding includes required codecs,
not simply disposable SQL string generation. `build_insert_many` is only about
0.020–0.022 s/200 batches in those profiles: another tiny builder shortcut is not
supported as a large bulk win.

Point profiles locate synchronous SELECT compilation alongside begin/commit,
pool/runtime ownership and cleanup. They do not justify removing deadline or
cancellation protection. Public phase durations and unprofiled setup measurements
above prevent confusing profiled compilation costs with actual wall latency.

## Acquisition and incremental memory diagnostics

Separate capacity-one/eight-worker acquisition runs: three processes/backend,
three trials/adapter, 1,000 requests after 100 warmups. Median trial p99 ms:

| Backend | Raw admission | snekql admission | Core checkout |
| --- | ---: | ---: | ---: |
| SQLite | 1.304 | 5.231 | 4.604 |
| MariaDB | 2.356 | 7.810 | 6.778 |

Core checkout includes pool bookkeeping, not pure queue wait. Slower operation
service time can increase admission wait. Predetermined per-worker request counts
are **not a fairness test**; this does not identify a starvation bug.

Separate tracemalloc runs, three processes × three trials/adapter/case; warmed,
GC before each window. Point 200 ops/50 warmup; stream three scans/one warmup;
bulk 30 batches/three warmup. Median traced peak bytes:

| Backend / case | Raw | snekql | Core |
| --- | ---: | ---: | ---: |
| SQLite point | 19,782 | 51,841 | 75,952 |
| SQLite stream | 140,929 | 410,048 | 215,809 |
| SQLite bulk | 93,400 | 104,818 | 172,735 |
| MariaDB point | 279,839 | 853,786 | 336,487 |
| MariaDB stream | 702,634 | 839,690 | 742,548 |
| MariaDB bulk | 334,302 | 528,598 | 440,982 |

Includes tasks/latency/correctness recorders, not process/native peak memory or
startup/model declarations. RSS snapshots and current traced bytes are in full
reports, not leak or retained-result verdicts. The MariaDB point peak is higher;
this alone does not establish a leak or an optimization proposal. Memory timings
are instrumented and excluded from primary throughput.

## Provenance, exclusions and validation

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2; snekql 0.9.0,
aiosqlite 0.22.1, aiomysql 0.3.2, Pydantic 2.14.0, anyio 4.15.1,
SQLAlchemy 2.1.1, greenlet 3.5.6. Linux 7.2.8-9-omarchy/glibc 2.44;
i7-14700F, 28 logical CPUs, ~33.45 GB RAM, powersave, full affinity.
Private disk-backed Btrfs directories, SQLite WAL/NORMAL; MariaDB loopback TCP,
InnoDB redo flush at commit 1, binlog off. Session policy probes pass. No CPU
pinning, governor change or exclusive host control; large trial ranges retained.

All owned tests, primary timing, memory, profiles and follow-up timing ran
sequentially. Background launchers restored Python's default SIGINT handler;
private TMPDIR and `PYTHON_CONTEXT_AWARE_WARNINGS=1` throughout. Measurement source
reports are clean at the exact baseline above; scripts live outside the checkout.

**Eight excluded reports / 135 trial records remain published:**

- First successful SQLite point invocation excluded because its outer runner
  checked nonexistent `environment.git.dirty` rather than `environment.dirty`.
  The command itself succeeded; traceback/command/report retained. Fixed runner,
  restarted the primary series, no partial-success aggregation.
- Detected another checkout's experimental normal/lazy tests. Paused our parent
  orchestrator, let its current child finish, left unrelated work untouched, then
  repeated six potentially overlapping/boundary MariaDB timing reports.
- A later unrelated lazy suite overlapped the final MariaDB bulk memory report;
  repeated that report too, after waiting. Exclusion timing is conservatively
  estimated from process elapsed time, not exact start tracing.

Known overlaps are excluded rather than normalized away. This monitoring does
**not certify** an otherwise idle host or explain all drift; unrelated activity
can remain undetected. Full private process snapshots are not published.

Existing comparative-harness tests: **61 passed in 170.52 s**.
Ruff/format/ty/whitespace checks pass and are recorded with the PR. No new runtime/test implementation, unsafe source mutation,
or full-suite rerun is claimed for this evidence-only change. Prior #533 tests
are not presented as validation of a hypothetical prepared interface.

## Evidence and reproduction

**2,286 included trial records:** 1,080 primary comparative, 54 acquisition,
162 memory, 576 fixed-cost matrix, 54 phase, 216 setup, 144 stem-reuse.
Eighteen function profiles are separate diagnostics, not additional timing trials.

Under [`results/runtime-reassessment-534/`](results/runtime-reassessment-534/):

- `comparative-trials.csv`, `matrix-trials.csv`, `setup-trials.csv`,
  `stem-trials.csv`, `phase-trials.json`, `profile-functions.csv`.
- `comparative-reports.jsonl` (84 complete reports),
  `diagnostic-reports.jsonl` (28), `stem-reports.jsonl` (six).
  Each JSONL envelope contains original report name and complete report data;
  no trial distribution, policy, correctness or environment fields removed.
- `manifest.json`, `diagnose-manifest.json`, `stem-manifest.json`: exact argv,
  start/finish timestamps and exit status. Baseline/environment in main manifest.
- `excluded-reports.jsonl`, `exclusions-manifest.json`, `load-exclusions.json`:
  all excluded results, commands, reason and preflight traceback.

Raw artifacts/scripts/profiles:
`/home/crpier/.cache/snekql-reassessment/`. Owned temporary databases are removable
after confirming no owned server remains; unrelated sessions/files are untouched.

Use a clean checkout of the recorded revision with its locked dependencies and
native MariaDB tools. Save the following scripts together outside the checkout;
run from its root, using its `.venv/bin/python`. Set a private **disk-backed**
TMPDIR and `PYTHON_CONTEXT_AWARE_WARNINGS=1`. Run one process at a time. Report
scripts are measurement tools, not application interfaces or CI speed gates.

1. `run.py`: six primary rounds followed by three acquisition/memory rounds.
   Change its `repo` and output directory to your checkout/cache. Exact original
   commands also in manifest; outer metadata/load exclusions describe this capture.
2. `diagnose.py BACKEND matrix INDEX`: six fresh processes/backend, INDEX 0–5,
   alternating backend order. Then `phases` × three/backend, `setup` × three,
   `profile` × one and `bulk-profile` × one. Do not overlap modes.
3. `diagnose.py BACKEND stem INDEX`: three fresh processes/backend, INDEX 0–2,
   alternating backend order, after all other measurements complete.
4. Run harness tests separately: `uv run snektest tests/test_comparative_benchmarks.py`.

### `run.py`

```python
import json, os, signal, subprocess, sys, time
from pathlib import Path

signal.signal(signal.SIGINT, signal.default_int_handler)
r = Path(__file__).resolve().parent
repo = Path("/home/crpier/Projects/third-snekql")
env = os.environ | {"TMPDIR": str(r / "tmp"), "PYTHON_CONTEXT_AWARE_WARNINGS": "1"}
manifest = []


def run(label, args):
    cmd = [str(repo / ".venv/bin/python"), "-m", "benchmarks.compare", *args]
    entry = {"label": label, "argv": cmd, "started_ns": time.time_ns()}
    print("START", label, flush=True)
    with (
        (r / f"{label}.json").open("w") as out,
        (r / f"{label}.stderr").open("w") as err,
    ):
        p = subprocess.run(cmd, cwd=repo, env=env, stdout=out, stderr=err, timeout=240)
    entry.update(exit=p.returncode, finished_ns=time.time_ns())
    manifest.append(entry)
    (r / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if p.returncode:
        raise RuntimeError(label)
    d = json.loads((r / f"{label}.json").read_text())
    assert not d["environment"]["dirty"], d["environment"]
    print("DONE", label, flush=True)


for round in range(6):
    for backend in ("sqlite", "mariadb") if round % 2 == 0 else ("mariadb", "sqlite"):
        cases = [
            ("point", "point-read", 2000, 2000, 200, 256, 1),
            ("join", "join", 2000, 2000, 200, 256, 1),
            ("stream", "stream", 20000, 5, 1, 256, 1),
            ("bulk", "bulk", 2000, 100, 10, 64, 1),
            ("contention", "point-read", 2000, 2000, 200, 256, 8),
        ]
        cases = cases[round % 5 :] + cases[: round % 5]
        for name, workload, rows, ops, warmup, batch, workers in cases:
            run(
                f"timing-{round + 1}-{backend}-{name}",
                [
                    "--backend",
                    backend,
                    "--workload",
                    workload,
                    "--rows",
                    str(rows),
                    "--operations",
                    str(ops),
                    "--warmup",
                    str(warmup),
                    "--batch-size",
                    str(batch),
                    "--workers",
                    str(workers),
                    "--trials",
                    "6",
                ],
            )
for round in range(3):
    for backend in ("sqlite", "mariadb") if round % 2 == 0 else ("mariadb", "sqlite"):
        run(
            f"pool-{round + 1}-{backend}",
            [
                "--backend",
                backend,
                "--profile",
                "diagnostic",
                "--rows",
                "2000",
                "--operations",
                "1000",
                "--warmup",
                "100",
                "--workers",
                "8",
                "--trials",
                "3",
            ],
        )
        for name, rows, ops, warmup, batch in [
            ("point-read", 2000, 200, 50, 256),
            ("stream", 20000, 3, 1, 256),
            ("bulk", 2000, 30, 3, 64),
        ]:
            run(
                f"memory-{round + 1}-{backend}-{name}",
                [
                    "--backend",
                    backend,
                    "--profile",
                    "memory",
                    "--workload",
                    name,
                    "--rows",
                    str(rows),
                    "--operations",
                    str(ops),
                    "--warmup",
                    str(warmup),
                    "--batch-size",
                    str(batch),
                    "--trials",
                    "3",
                ],
            )
(r / "broad.done").write_text("success\n")
```

### `diagnose.py`

```python
"""Standalone diagnostic; public workloads plus separate cProfile capture."""

import asyncio
import cProfile
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks._comparison_contract import Record
from snekql import sqlite, mariadb
from snekql.testing.mariadb import temporary_mariadb_server

backend, mode, index_text = sys.argv[1:]
index = int(index_text)
root = Path(__file__).resolve().parent


@asynccontextmanager
async def database(observer=None):
    if backend == "sqlite":
        from benchmarks._comparison_sqlite import seed
        from benchmarks._models_sqlite import BenchUser, BenchWrite

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostic.db"
            await seed(path, 2000)
            async with await sqlite.Database.initialize(
                sqlite.Config(database=path, pool_size=1, durability="normal"),
                observer=observer,
            ) as db:
                yield sqlite, BenchUser, BenchWrite, db
    else:
        from benchmarks._comparison_mariadb import seed
        from benchmarks._models_mariadb import BenchUser, BenchWrite

        async with temporary_mariadb_server(transports={"tcp"}) as server:
            config = server.config(pool_size=1)
            await seed(config, 2000)
            async with await mariadb.Database.initialize(
                config, observer=observer
            ) as db:
                yield mariadb, BenchUser, BenchWrite, db


async def main():
    samples = []
    events = defaultdict(lambda: {"count": 0, "seconds": 0.0})
    active = False

    def observe(event):
        if active and event.phase == "finish":
            assert event.outcome == "success", event
            events[event.kind]["count"] += 1
            events[event.kind]["seconds"] += event.duration_seconds

    async with database(observe if mode == "phases" else None) as (
        api,
        model,
        write,
        db,
    ):

        def build(shape):
            q = api.select(model)
            if shape == "named":
                q = q.project(
                    Record, id=model.id, email=model.email, payload=model.payload
                )
            return q.where(model.id.eq(42))

        def check(rows):
            assert len(rows) == 1
            row = rows[0]
            assert (row.id, row.email, row.payload) == (
                42,
                "user42@example.com",
                "x" * 32,
            )

        if mode in ("matrix", "profile"):
            cases = [
                (s, b, t)
                for s in ("named", "model")
                for b in (False, True)
                for t in (True, False)
            ]
            cases = cases[index % 8 :] + cases[: index % 8]
            if index % 2:
                cases = list(reversed(cases))
            for shape, rebuild, reuse in cases:
                prebuilt = build(shape)
                label = f"{shape}-{'rebuilt' if rebuild else 'prebuilt'}-{'shared' if reuse else 'per-operation'}"

                async def run(count):
                    if reuse:
                        async with db.transaction() as tx:
                            for _ in range(count):
                                check(
                                    await tx.fetch_all(
                                        build(shape) if rebuild else prebuilt
                                    )
                                )
                    else:
                        for _ in range(count):
                            async with db.transaction() as tx:
                                check(
                                    await tx.fetch_all(
                                        build(shape) if rebuild else prebuilt
                                    )
                                )

                await run(200)
                if mode == "profile":
                    p = cProfile.Profile()
                    p.enable()
                    await run(2000)
                    p.disable()
                    p.dump_stats(str(root / f"profile-{backend}-{label}.prof"))
                else:
                    for trial in range(6):
                        start = time.perf_counter()
                        cpu = time.thread_time()
                        await run(2000)
                        cpu = time.thread_time() - cpu
                        elapsed = time.perf_counter() - start
                        samples.append(
                            dict(
                                shape=shape,
                                rebuild=rebuild,
                                shared_transaction=reuse,
                                trial=trial + 1,
                                operations=2000,
                                seconds=elapsed,
                                ops_s=2000 / elapsed,
                                main_thread_us=cpu * 1e6 / 2000,
                            )
                        )
        elif mode == "stem":
            stem = api.select(model).project(
                Record, id=model.id, email=model.email, payload=model.payload
            )

            def query(identity, style):
                base = (
                    stem
                    if style == "stem"
                    else api.select(model).project(
                        Record, id=model.id, email=model.email, payload=model.payload
                    )
                )
                return base.where(model.id.eq(identity))

            for trial in range(6):
                cases = [
                    (style, shared)
                    for style in ("full", "stem")
                    for shared in (False, True)
                ]
                cases = cases[(trial + index) % 4 :] + cases[: (trial + index) % 4]
                for style, shared in cases:

                    async def one(tx, i):
                        identity = i % 2000 + 1
                        rows = await tx.fetch_all(query(identity, style))
                        assert len(rows) == 1
                        row = rows[0]
                        assert (row.id, row.email, row.payload) == (
                            identity,
                            f"user{identity}@example.com",
                            "x" * 32,
                        )

                    async def run(count):
                        if shared:
                            async with db.transaction() as tx:
                                for i in range(count):
                                    await one(tx, i)
                        else:
                            for i in range(count):
                                async with db.transaction() as tx:
                                    await one(tx, i)

                    await run(200)
                    start = time.perf_counter()
                    cpu = time.thread_time()
                    await run(2000)
                    cpu = time.thread_time() - cpu
                    elapsed = time.perf_counter() - start
                    samples.append(
                        dict(
                            style=style,
                            shared_transaction=shared,
                            trial=trial + 1,
                            operations=2000,
                            seconds=elapsed,
                            ops_s=2000 / elapsed,
                            main_thread_us=cpu * 1e6 / 2000,
                        )
                    )
        elif mode == "setup":
            # Private compiler is a diagnostic only, not a proposed public plan interface.
            from snekql._query_codec import DialectQueryCodec

            codec = DialectQueryCodec.for_backend(backend)
            for shape in ("named", "model"):
                q = build(shape)
                compiled = q.compile()
                assert compiled.params == (42,)
                plan = codec.compile_select_plan(q, cardinality="many")
                assert (plan.sql, plan.params) == (compiled.sql, compiled.params)
                actions = [
                    ("builder", lambda: build(shape)),
                    ("sql", q.compile),
                    (
                        "full-plan",
                        lambda: codec.compile_select_plan(q, cardinality="many"),
                    ),
                ]
                for name, action in actions:
                    for _ in range(1000):
                        action()
                for trial in range(6):
                    rotated = (
                        actions[(trial + index) % 3 :] + actions[: (trial + index) % 3]
                    )
                    for name, action in rotated:
                        start = time.perf_counter()
                        cpu = time.thread_time()
                        for _ in range(10000):
                            result = action()
                        cpu = time.thread_time() - cpu
                        elapsed = time.perf_counter() - start
                        samples.append(
                            dict(
                                shape=shape,
                                action=name,
                                trial=trial + 1,
                                operations=10000,
                                seconds=elapsed,
                                ops_s=10000 / elapsed,
                                main_thread_us=cpu * 1e6 / 10000,
                            )
                        )
        elif mode == "phases":
            # Public observer durations are nested diagnostics, not additive phases.
            for label in ("empty-transaction", "point-read", "bulk-64"):
                for trial in range(3):
                    events.clear()
                    times = defaultdict(float)
                    count = 1000 if label != "bulk-64" else 50

                    # Distinct IDs throughout this server lifetime; include warmup below.
                    async def one(i):
                        async def stage(name, action):
                            start = time.perf_counter()
                            result = await action()
                            times[name] += time.perf_counter() - start
                            return result

                        def sync_stage(name, action):
                            start = time.perf_counter()
                            result = action()
                            times[name] += time.perf_counter() - start
                            return result

                        if label == "empty-transaction":
                            tx = db.transaction()
                            await stage("entry", tx.__aenter__)
                            await stage("exit", lambda: tx.__aexit__(None, None, None))
                        elif label == "point-read":
                            q = sync_stage("query_build", lambda: build("named"))
                            tx = db.transaction()
                            await stage("entry", tx.__aenter__)
                            rows = await stage("fetch", lambda: tx.fetch_all(q))
                            await stage("exit", lambda: tx.__aexit__(None, None, None))
                            check(rows)
                        else:
                            start_id = (trial * 1000 + i) * 64 + 1
                            inputs = sync_stage(
                                "input_models",
                                lambda: [
                                    write(
                                        id=n,
                                        email=f"user{n}@example.com",
                                        payload="x" * 32,
                                    )
                                    for n in range(start_id, start_id + 64)
                                ],
                            )
                            q = sync_stage(
                                "insert_query", lambda: api.insert_many(write, inputs)
                            )
                            tx = db.transaction()
                            await stage("write_entry", tx.__aenter__)
                            await stage("write_execute", lambda: tx.execute(q))
                            await stage(
                                "write_exit", lambda: tx.__aexit__(None, None, None)
                            )
                            q = sync_stage(
                                "read_query",
                                lambda: (
                                    api.select(write)
                                    .project(
                                        Record,
                                        id=write.id,
                                        email=write.email,
                                        payload=write.payload,
                                    )
                                    .where(
                                        write.id.gte(start_id)
                                        & write.id.lt(start_id + 64)
                                    )
                                    .order_by(write.id.asc())
                                ),
                            )
                            tx = db.transaction()
                            await stage("read_entry", tx.__aenter__)
                            rows = await stage("read_fetch", lambda: tx.fetch_all(q))
                            await stage(
                                "read_exit", lambda: tx.__aexit__(None, None, None)
                            )
                            assert len(rows) == 64
                            for n, row in enumerate(rows, start_id):
                                assert (row.id, row.email, row.payload) == (
                                    n,
                                    f"user{n}@example.com",
                                    "x" * 32,
                                )

                    # Warmup is outside captured event/timing samples.
                    for i in range(10):
                        await one(i)
                    events.clear()
                    times.clear()
                    active = True
                    start = time.perf_counter()
                    cpu = time.thread_time()
                    for i in range(10, count + 10):
                        await one(i)
                    cpu = time.thread_time() - cpu
                    elapsed = time.perf_counter() - start
                    active = False
                    samples.append(
                        dict(
                            label=label,
                            trial=trial + 1,
                            operations=count,
                            seconds=elapsed,
                            main_thread_us=cpu * 1e6 / count,
                            phase_us={k: v * 1e6 / count for k, v in times.items()},
                            events=dict(events),
                        )
                    )
        elif mode == "bulk-profile":
            # Existing equivalent committed INSERT + verified readback workload.
            # Build workload locally to retain this database's public runtime and ownership.
            async def bulk(start_id):
                q = api.insert_many(
                    write,
                    [
                        write(id=n, email=f"user{n}@example.com", payload="x" * 32)
                        for n in range(start_id, start_id + 64)
                    ],
                )
                async with db.transaction() as tx:
                    await tx.execute(q)
                q = (
                    api.select(write)
                    .project(
                        Record, id=write.id, email=write.email, payload=write.payload
                    )
                    .where(write.id.gte(start_id) & write.id.lt(start_id + 64))
                    .order_by(write.id.asc())
                )
                async with db.transaction() as tx:
                    rows = await tx.fetch_all(q)
                assert len(rows) == 64
                for n, row in enumerate(rows, start_id):
                    assert (row.id, row.email, row.payload) == (
                        n,
                        f"user{n}@example.com",
                        "x" * 32,
                    )

            for i in range(10):
                await bulk(i * 64 + 1)
            p = cProfile.Profile()
            p.enable()
            for i in range(10, 210):
                await bulk(i * 64 + 1)
            p.disable()
            p.dump_stats(str(root / f"profile-{backend}-bulk.prof"))
        else:
            raise ValueError(mode)
    print(
        json.dumps(
            dict(
                backend=backend,
                mode=mode,
                process_index=index,
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


if __name__ == "__main__":
    asyncio.run(main())
```
