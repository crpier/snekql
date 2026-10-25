# Long-lived service soak — 2026-10-25

Tracking: #538; admission defect: #540; implementation: #541.

## Result and scope

All four initial runs completed, reconciled their acknowledged writes, drained
and closed their pools, and passed the descriptor/native-thread checks. The
workload also exposed a real admission stall during development; that failed
run is preserved separately, not averaged into success.

These are **120-second measured runs**, not day-long service certification or
comparative performance results. They validate the new harness and provide
bounded initial evidence. The manual **Service soak** workflow defaults to
30-minute runs against SQLite and MariaDB 11.4 at pool sizes one and four.
That workflow has not been run as part of this report. Real transport/storage/
process fault drills and a refreshed raw/Core performance comparison are still
separate units of work.

## Source and environment

- Clean measured revision: `52d57db1690bdc696be189cf97dfa9f3015537c4`.
  Every environment record has `dirty: false`. Subsequent changes in this PR
  add evidence/reporting prose and raw artifacts, not workload/runtime changes.
- CPython 3.15.0, GIL-enabled, default asyncio on Linux
  `7.2.8-9-omarchy-x86_64`, glibc 2.44.
- SQLite 3.53.1, private file-backed WAL, default NORMAL durability.
- Native MariaDB **13.0.2**, owned loopback TCP server with the helper's defaults.
  This is extra local evidence, not a claim that the long run used MariaDB 11.4
  or any particular maintained LTS. Maintained releases have native smoke/full
  correctness evidence from CI below.
- Installed distribution versions, selected settings, engine versions and PIDs
  are recorded in each JSONL file. The source-checkout workload uses validated
  builder models, atomic increments, full/early streams and public pool stats.
- Runs used fresh processes and ran sequentially after this work's local suite.
  This was a shared developer machine, not an isolated benchmark host; other
  work existed in another checkout. Do not infer capacity recommendations or
  cross-backend throughput rankings.

## Invocation

For each `backend` in `sqlite mariadb`, then each `pool` in `1 4`:

```sh
TMPDIR="$owned_root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
  uv run python -m soak.service --backend "$backend" \
  --pool-size "$pool" --workers 16 --duration 120 --warmup 5 \
  --sample-interval 5 --rows 257 --batch-size 32 \
  --slow-consumer 0.005 --burst-interval 1 --seed 538
```

Stdout, stderr and exit status were retained independently. The resource root
was on the home filesystem, not the quota-limited system temporary filesystem.
Background launches reset SIGINT/SIGQUIT to normal dispositions before exec;
see the local-validation caveat below. `run-times.txt` records UTC start/end.
See [the service guide](README.md) for full reproduction, bounds and schema.

## Observations

Operation counts and write counts below exclude warm-up. A completed operation
includes transaction acquisition, database work, validation and commit/cleanup;
stream operations also include intentional consumer pauses. Duration includes
worker/burst draining. Queued cancellations include measured bursts only.

| Backend / pool | Elapsed s | Operations | Writes | Queued cancellations | RSS delta KiB | Max loop delay ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite / 1 | 120.748 | 8,688 | 2,176 | 79 | +52 | 6.978 |
| SQLite / 4 | 120.126 | 25,691 | 6,425 | 83 | +92 | 7.026 |
| MariaDB / 1 | 120.395 | 7,737 | 1,936 | 98 | +216 | 9.949 |
| MariaDB / 4 | 120.159 | 22,901 | 5,727 | 80 | +236 | 12.299 |

Across these runs: 65,017 measured operations, 16,264 measured acknowledged
writes and 340 measured queued-waiter cancellations. Final reconciliation also
included warm-up writes: respectively 2,272, 6,704, 2,032 and 5,978 total ledger
increments in table order. Every run had zero acquisition failures and zero
discarded connections. Drained occupied slots/waiters were zero; shutdown was
closed with zero occupied slots. A fresh read after reconciliation succeeded.

Drained file-descriptor and native-thread deltas were **zero on every target**.
Current RSS ranges (baseline through drained sample), in table order, were
50,676–50,728; 51,404–51,496; 50,340–50,556; and 50,772–51,008 KiB. Small retained
RSS changes are observations, not proof of a leak or proof of leak freedom.
Sampling runs GC and can perturb the event loop. The short duration, bounded
fixture and single workload do not cover gradual growth over hours or days.
Server-process memory is not measured.

## Admission defect found and fixed

Before the runtime fix, the sustained multi-slot native CLI regression failed
with acquisition timeouts after 37.19 seconds. A separate development trace
observed capacity three, occupied two, five waiters, and all pending tasks
awaiting admission. The saturation task retained two leases and waited for the
third; no future release existed to wake the sleeping queue head.

The FIFO gate notified on release/cancellation, but not on a successful admission
that advanced the head while leaving free capacity. Later tickets could re-park
before the head ran. The fix notifies waiting tickets whenever admission leaves
capacity available. The same native regression then passed, followed by all
focused checks and the complete CI matrix.

The pre-fix regression log and task-stack observation came from a **dirty
pre-commit development tree**, not the clean measured revision. They are bounded
regression evidence, not an exhaustive scheduler proof. They remain separate
from successful JSONL measurements under `results/2026-10-25-service/`.

## Validation

[CI run 40234570578](https://github.com/crpier/snekql/actions/runs/40234570578)
completed successfully on the exact measured revision:

- Validate: **4,114 passed** normally (525.39 seconds) and **4,114 passed** with
  forced lazy imports (538.49 seconds).
- Full native MariaDB jobs: 10.11, 11.4, 11.8, 12.2 and 12.3 all succeeded.
- SQLite environment jobs: Linux system/managed, macOS and Windows all succeeded.
- Typing/consumer conformance, Ruff lint/format, generated interfaces, lock,
  builds and isolated artifacts succeeded. CodeQL and dependency review also
  succeeded on the PR.
- Local ty, Ruff lint/format, generated-interface and lock checks passed.

**Local full-suite caveat:** an initial background launcher inherited ignored
SIGINT from its shell. That invalid local run reported **4,110 passed and four
errors**, all CLI password-authentication shutdown cases. The process's observed
`SigIgn` included SIGINT; the CLI therefore did not get its normal Ctrl-C handling.
All four affected cases passed on a foreground rerun with normal signal handling
(25.19 seconds). The failed full-suite attempt is not relabeled as green, and
its result is distinct from the complete green CI runs. The soak measurements
were launched after this correction. No library/test-helper fix was made for
this launcher mistake.

## Evidence inventory

[`results/2026-10-25-service/`](results/2026-10-25-service/) contains:

- Four complete `*.jsonl`, `*.stderr` and `*.status` triplets; every status is zero.
- UTC run times, compact CI job results and Validate log excerpts.
- Separate pre-fix admission regression/task-stack evidence.
- Invalid local full-suite summary and corrected signal-sensitive case results.
- `sha256.json` covering every other evidence file.

Complete local validation logs remain in the owned cache root
`~/.cache/snekql-service-tests-gyx5ceVY/`. The committed report is self-contained
for the measured runs; full CI logs are linked above.
