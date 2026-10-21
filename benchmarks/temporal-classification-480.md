# Temporal classification cache — #480

Measured 2026-10-21 against clean baseline `cb4db57` and clean implementation
`0afeea3`. This branch starts from `main`, **without** #479's projection changes.

## Change

Each column retains its successfully resolved temporal classification, including
“not temporal.” An unbound column or an annotation containing a forward reference
is **not** cached. The latter matters: a module-level name can become a temporal
type after initial declaration checks. The cache is descriptor-local, follows the
existing private codec-cache lifetime, and remains writable after metadata freezes
so deferred foreign-key binding can finish normally. Aliases retain the source
annotation and can safely copy the immutable cached result.

The encode/decode methods still call the overridable classification method; no
subclass dispatch, temporal-meaning validation, native precision check, or exact
write requirement is bypassed. No global/type-level cache or dependency changes.

## Isolated encoding results

The public column `encode(..., backend=..., write=True)` method was measured
separately from model construction, SQL compilation, driver work and readback.
For each case: 1,000 warmup calls, 50,000 timed calls, six trials with rotating
case order. GC was collected before and disabled during each timed loop. Wire
values were checked before/after timing. See the complete script below.

Primary phases were **baseline / candidate / baseline / candidate**. Thus each
cell below is a median of 12 trials and both B/C/B and C/B/C orderings occur.
Two initial pilot phases were excluded because a short baseline regression-test
run overlapped the second phase; no tests ran during retained measurements.

| Backend | Column / storage | Baseline encodes/s | Candidate encodes/s | Ratio |
| --- | --- | ---: | ---: | ---: |
| SQLite | Integer | 507,266 | 859,888 | 1.70× |
| SQLite | Text | 522,382 | 893,604 | 1.71× |
| SQLite | UTC / Text | 368,593 | 537,739 | 1.46× |
| SQLite | Civil / Text | 420,317 | 636,184 | 1.51× |
| MariaDB | Integer | 505,919 | 867,223 | 1.71× |
| MariaDB | Text | 507,180 | 877,747 | 1.73× |
| MariaDB | UTC / DateTime(6) | 632,601 | 1,124,589 | 1.78× |
| MariaDB | Civil / DateTime(6) | 619,612 | 1,109,829 | 1.79× |

These are warm-column encoding throughput improvements, **not** whole-query
speedups. They do not measure model-declaration cost or concurrent cold binding.

## Verified bulk: noisy end-to-end observations

Existing `benchmarks.compare`, 50 operations/trial, 64 rows/batch, five warmup,
six rotating raw/snekql/SQLAlchemy trials per phase. An operation includes committed
insertion and verified readback in another transaction. Medians of 12 trials:

| Backend | Adapter | Baseline ops/s | Candidate ops/s |
| --- | --- | ---: | ---: |
| SQLite | raw | 2173.1 | 2288.9 |
| SQLite | snekql | 271.0 | 364.0 |
| SQLite | SQLAlchemy | 496.4 | 483.2 |
| MariaDB | raw | 122.1 | 175.1 |
| MariaDB | snekql | 110.6 | 123.0 |
| MariaDB | SQLAlchemy | 119.7 | 136.0 |

The observed snekql ratios are 1.34× / 1.11×, but the controls also move,
particularly MariaDB raw throughput (+43%). **Do not attribute these end-to-end
ratios solely to this cache or claim a reliable MariaDB bulk speedup.** The
isolated encoding measurements and profile establish the CPU work reduction;
the disk-backed composite workload needs a more controlled capacity study.

Individual snekql phase medians B/C/B/C: SQLite 304.7 / 349.9 / 266.9 / 389.9;
MariaDB 101.3 / 123.1 / 122.5 / 123.0 ops/s.

| Backend | Metric (median of trial summaries) | Baseline ms | Candidate ms |
| --- | --- | ---: | ---: |
| SQLite | p99 operation latency | 4.688 | 4.244 |
| SQLite | maximum heartbeat lateness | 1.829 | 1.871 |
| MariaDB | p99 operation latency | 10.991 | 9.970 |
| MariaDB | maximum heartbeat lateness | 1.363 | 1.209 |

Separate three-trial allocation diagnostics (10 operations, two warmup) show
median incremental traced Python peaks of 91.6 → 92.5 KiB (SQLite) and
398.3 → 398.6 KiB (MariaDB). Timings from these diagnostic runs are excluded.
The cache adds a small tuple/attribute per resolved descriptor, including negative
results; setup allocations are excluded from this diagnostic, so it does **not**
establish zero added memory. This is not total/native memory or peak RSS.

A separate SQLite cProfile run of 1,000 bulk operations + 100 warmup reports
213,416 `_temporal_type` calls in both revisions. Instrumented cumulative time
falls from 0.941 s to 0.018 s; `_encode_value` falls from 1.560 s to 0.623 s.
These nested profile times are not additive and are not throughput estimates.

## Reproduction, evidence and limits

CPython 3.15.0, SQLite 3.53.1, MariaDB 13.0.2, Pydantic 2.14.0, anyio 4.15.1,
aiosqlite 0.22.1, aiomysql 0.3.2, SQLAlchemy 2.1.1, greenlet 3.5.6. Intel
i7-14700F, 28 logical CPUs, approximately 33.45 GB RAM, `powersave` governor;
no CPU pinning or host-wide background-load control. Both revisions use private
**disk-backed Btrfs** temporary databases, SQLite WAL/NORMAL and MariaDB redo
flush policy 1 with binary logging off. Do not compare absolute figures with
#483's tmpfs investigation or combine the gains with #479's unmerged changes.

Use a fresh private disk-backed directory as `TMPDIR`, and set
`PYTHON_CONTEXT_AWARE_WARNINGS=1`. In each revision/backend run:

```sh
uv run python -m benchmarks.compare --backend sqlite --workload bulk \
  --rows 2000 --operations 50 --trials 6 --warmup 5 --batch-size 64
# Repeat with --backend mariadb.
# Allocation diagnostics: --operations 10 --trials 3 --warmup 2 --profile memory.
# CPU profile: python -m cProfile -o PATH -m benchmarks.compare with
# --adapter snekql --operations 1000 --trials 1 --warmup 100.
```

The [runtime manifest](results/temporal-classification-480/manifest.json) retains
commands, environment, report headers and session policies for eight primary
bulk runs and four memory runs; [trials.csv](results/temporal-classification-480/trials.csv)
contains all 180 flattened trial records. `run` joins the manifest; `session_policy`
references its policy dictionary. Lists remain JSON inside CSV cells; empty
optional fields are null. All commands exit zero with empty stderr.
[Encoding metadata](results/temporal-classification-480/encoding-manifest.json)
and [192 encoding trials](results/temporal-classification-480/encoding-trials.csv)
retain source paths, revisions, durations and operation counts. Original JSON,
pilots, scripts, mutation-test logs and profiles remain locally in
`/home/crpier/.cache/snekql-480/`.

## Regression coverage

Four new public-interface cases protect module-level late temporal annotations,
deferred native temporal foreign keys and their exact write/predicate precision,
alias meaning checks, and independent ordinary/nullable temporal columns.
They pass on the unchanged baseline as well. The first test rejects a premature
negative-cache implementation; removing the frozen-cache allowance fails three
cases. These unsafe variants were reverted. No cache-hit counts, private helper
assertions, or machine-speed assertions are added to tests.

Focused declaration/temporal/backend tests: **153 passed**. Static checks pass;
full-suite and CI status are recorded in the implementation PR.

## Isolated encoding script

Save outside either source tree; execute from each clean revision with the same
interpreter/dependencies. The source-directory insertion ensures that the selected
worktree, not the editable installation's other checkout, is measured.

```python
import gc
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import ClassVar

sys.path.insert(0, os.getcwd())
from snekql import mariadb, sqlite
import snekql.storage


class SQLiteRecord[S = sqlite.Pending](sqlite.Model[S]):
    __row_type__: ClassVar[sqlite.ReadType[SQLiteRecord[sqlite.Row]]]
    number: sqlite.Col[int] = sqlite.Integer()
    text: sqlite.Col[str] = sqlite.Text()
    instant: sqlite.Col[sqlite.UtcDatetime] = sqlite.Text()
    civil: sqlite.Col[sqlite.LocalDatetime] = sqlite.Text()


class MariaRecord[S = mariadb.Pending](mariadb.Model[S]):
    __row_type__: ClassVar[mariadb.ReadType[MariaRecord[mariadb.Row]]]
    number: mariadb.Col[int] = mariadb.Integer()
    text: mariadb.Col[str] = mariadb.Text()
    instant: mariadb.Col[mariadb.UtcDatetime] = mariadb.DateTime()
    civil: mariadb.Col[mariadb.LocalDatetime] = mariadb.DateTime()


instant = sqlite.UtcDatetime(datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC))
civil = sqlite.LocalDatetime(datetime(2026, 1, 2, 3, 4, 5, 123456))
trials = []
for backend, model in [("sqlite", SQLiteRecord), ("mariadb", MariaRecord)]:
    cases = [
        ("integer", model.number, 7, 7),
        ("text", model.text, "payload", "payload"),
        (
            "utc",
            model.instant,
            instant,
            "2026-01-02T03:04:05.123456Z"
            if backend == "sqlite"
            else "2026-01-02 03:04:05.123456",
        ),
        (
            "civil",
            model.civil,
            civil,
            "2026-01-02T03:04:05.123456"
            if backend == "sqlite"
            else "2026-01-02 03:04:05.123456",
        ),
    ]
    for trial in range(6):
        for name, column, value, expected in cases[trial % 4 :] + cases[: trial % 4]:
            encode = column.encode
            for _ in range(1000):
                assert encode(value, backend=backend, write=True) == expected
            gc.collect()
            gc.disable()
            try:
                start = time.perf_counter()
                for _ in range(50000):
                    actual = encode(value, backend=backend, write=True)
                elapsed = time.perf_counter() - start
            finally:
                gc.enable()
            assert actual == expected
            trials.append(
                dict(
                    backend=backend,
                    case=name,
                    trial=trial + 1,
                    operations=50000,
                    elapsed_seconds=elapsed,
                    encodes_per_second=50000 / elapsed,
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
            module=snekql.storage.__file__,
            python=sys.version,
            warmup_per_trial=1000,
            gc_during_timing=False,
            trials=trials,
        )
    )
)
```
