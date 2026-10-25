# Real fault-drill evidence — 2026-10-25

Tracking: #544; native stream cleanup defect: #545; implementation PR: #546.
This is unit 2, following the long-lived [service soak](service-findings-2026-10-25.md).

## Source and procedure

All **12 clean-revision trials passed**: three fresh-process repetitions each of
`stream-cut`, `commit-blackhole`, `restart-load` and `sqlite-full`, in that order
within each repetition. Failed development attempts remain separate from these
trials; no retries, averaging or outlier removal converted a failed trial to a pass.

- Exact source: `97224032ff4360ecef0f4a1105945cdc1d7144fc`. Every trial's environment
  record has `dirty: false`. Later report/artifact changes do not alter runtime or
  workload behavior.
- CPython 3.15.0, Linux `7.2.8-9-omarchy-x86_64`, glibc 2.44, default asyncio.
- Native MariaDB **13.0.2**, SQLite **3.53.1**. Maintained MariaDB releases have
  separate native CI evidence below; the local trials were not run on 11.4.
- Each JSONL retains installed distribution versions, actual engine and effective
  scenario settings. Native MariaDB servers use owned disposable data and loopback
  TCP. SQLite runs in a distinct user/private mount namespace on its own tmpfs.
- Trials ran sequentially before this work's complete local suite, on a shared
  developer machine. Timing is not compared and no capacity claim is made.

For each trial and scenario, from the clean source checkout:

```sh
TMPDIR="$owned_root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
  uv run python -m soak.faults --scenario "$scenario" \
  > "$scenario-$trial.jsonl" 2> "$scenario-$trial.stderr"
printf '%s\n' "$?" > "$scenario-$trial.status"
```

The actual coordinator stops at the first nonzero status; all 12 statuses are
zero and all 12 stderr files are empty. Background launching reset SIGINT/SIGQUIT
before exec. UTC start/end and status lines are preserved in `run-times.txt`.
See [the fault guide](FAULTS.md) for exact fixed fixtures, handshakes, deadlines,
requirements, public checks and failure modes.

## Observations

| Scenario | Trials | Observed fault placement | Required result, observed every time |
| --- | ---: | --- | --- |
| Stream transport cut | 3/3 | First delivered IDs 1–4; 21,554 total server-to-client bytes forwarded before socket abort, less than the 16,777,216-byte complete payload. | Exactly four rows delivered, with validated ordered prefix/payload; native `connection_loss`; failed Transaction unusable; one discarded lease; fresh read returns 42. The harness allows extra buffered rows before failure rather than relying on the immediately next fetch failing. |
| COMMIT reply blackhole | 3/3 | One real COMMIT forwarded after the insert, server OK observed but withheld from the driver while TCP stayed open. | One-second deadline raises `DatabaseOperationTimeoutError`; public outcome `unknown`; fresh read reconciles exactly operation key 544 / value 7; one discarded lease; no COMMIT replay before recovery. |
| Server restart under load | 3/3 | Four running queries independently visible in the owned server's process list; four occupied slots and four queued callers in the public snapshot. Helper stops the actual server, then starts a new one on the same port/data directory. | Four active `connection_loss` failures and four queued `DatabaseRuntimeError`s per trial; four discarded active leases; known IDs 1–4 preserved; the same Database commits and reads new ID 5 after restart. |
| SQLite filesystem full | 3/3 | Distinct user/mount namespaces; 4,194,304-byte tmpfs filled to zero available blocks; actual OS ENOSPC (28), followed by native SQLITE_FULL (13). | Public commit outcome `unknown`, not an invented rejection; free filler, await owned detached cleanup, reconcile only ID 1, then commit/read new ID 3. Failed ID 2 absent. One discarded lease. |

Every trial drained to zero occupied slots and waiters, verified fresh work, and
closed with state `closed` and zero occupied slots. Successful summaries occur
after the owned proxy/server/namespace controls complete. These snapshots are
not native-descriptor or memory-leak measurements; resource trends belong to
the separate service soak.

SQLite's observed `unknown` outcome is intentional fail-closed evidence: the
error did not acknowledge a COMMIT. Reconciliation establishes the selected
fixture's persisted result. Do not turn a storage error or transient category
into permission to replay arbitrary non-idempotent writes.

## Defect found by the real stream cut

The first real-cut implementation failed against the pre-fix runtime: after a
native read lost the socket, aiomysql cursor cleanup tried to drain a dead reader
and raised `AttributeError: 'NoneType' object has no attribute 'readexactly'`.
That cleanup error replaced the classified native connection-loss error; the
public ExecutionError's failure metadata was absent. Simulated replies had not
reproduced this dead-reader condition.

The adapter-local fix detaches a cursor whose native connection is already closed
instead of draining it again. It does not parse AttributeError messages or invent
a category. The same CLI test passed after the fix; existing raw completion,
validation, cancellation and simulated late-fault tests also passed.

Pre-fix regression/debug logs are preserved separately. They came from a dirty
pre-commit development tree, **not** the clean measured revision. An initial
storage harness attempt also incorrectly required immediate zero occupancy after
a SQLite error; that was corrected to wait for the documented detached physical
cleanup through public stats. No SQLite runtime change was needed for that
harness assumption. Its failed development output is retained as such.

## Validation

The complete local suite passed: **4,122 tests in 982.37 seconds**, exit status
zero, with normal signal dispositions verified in the launched Python process.
The eight new native CLI/metadata cases passed, as did the existing late-stream,
raw completion/validation, ownership and cancellation coverage.

[CI run 40239794416](https://github.com/crpier/snekql/actions/runs/40239794416)
passed on the exact measured source revision:

- Validate: **4,122 tests** normally (587.38 seconds) and **4,122 tests** with
  forced lazy imports (557.19 seconds).
- Native full-suite jobs: MariaDB 10.11, 11.4, 11.8, 12.2 and 12.3 all succeeded.
  The non-optional stream/commit/restart CLI cases ran in each full suite.
- SQLite targets: Linux managed/system-library, macOS and Windows succeeded.
- Typing and consumer conformance, Ruff lint/format, generated interfaces, lock,
  builds and isolated artifact smoke tests all succeeded. CodeQL and dependency
  review also passed for the PR.
- Local ty, Ruff lint/format, generated-interface and lock checks passed.

This validates the changed runtime and harness, not the absence of unrelated
security problems. GitHub reported preexisting lockfile alerts for certifi
(critical) and opentelemetry-api (medium); this PR changes neither dependency.
Dependency remediation and release-candidate revalidation remain separate.

## Boundaries

- The proxy uses plaintext, bounded MySQL framing on owned loopback sockets. It
  withholds actual response bytes; it does not certify TLS, compressed/multi-packet
  protocols, production middleboxes, NAT, routing or all IP packet-loss patterns.
- Restart is real but cooperative, with read-only work in flight and acknowledged
  writes before/after. It is not SIGKILL/power-loss or replicated failover. The
  separate COMMIT blackhole covers write uncertainty at the response boundary.
- Tmpfs ENOSPC is real bounded-filesystem exhaustion, not persistent-media,
  controller, fsync-failure or arbitrary-filesystem certification. No host mount,
  sudo, machine networking or normal application database is modified.
- Namespace denial is an explicit nonzero CLI result, never a storage pass. The
  ordinary suite tests the success-or-explicit-isolation-rejection contract; its
  green status alone cannot certify storage execution. The local three storage
  trials here **did actually execute ENOSPC**. The stricter manual fault workflow
  requires actual success, but has not been executed for this report.
- Migration-process termination stays deferred while #477 changes that contract.
  These bounded drills do not establish long-term stability, comparative performance
  or overall release/security readiness. Rerun against the release candidate after
  dependency/runtime changes.

## Evidence

`results/2026-10-25-faults/` contains 12 JSONL/stderr/status triplets, UTC run times,
pre-fix and storage-development failures, validation summaries and a SHA-256
manifest covering every other file. Complete local logs remain at
`~/.cache/snekql-real-faults-dpqpWzqm/`.
