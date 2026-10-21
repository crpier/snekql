# asyncmy lifecycle investigation — 2026-10-21

Tracking: [#487](https://github.com/crpier/snekql/issues/487).
Follow-up to the performance work in [#484](https://github.com/crpier/snekql/pull/484).

**Hold a driver switch.** asyncmy 0.2.16 passes the simple abandoned-stream case,
but its public `SSCursor.close()` does not safely complete the multi-result case
below. This is a raw-driver finding, not a failure observed through snekql.
Production code and dependencies remain unchanged.

## Results

Both drivers used one privately owned MariaDB 13.0.2 server per command,
loopback TCP, autocommit enabled, utf8mb4, and multi-statements explicitly enabled.
Environment: CPython 3.15.0, aiomysql 0.3.2, asyncmy 0.2.16, Linux x86-64.
The asyncmy dependency was installed only in a pinned uv overlay.

The first result contains 4,096 rows with a 1,024-character payload, approximately
4 MiB before protocol overhead. The application reads only the first row. In the
multi-result case, an equally large second result and a third scalar result
follow. Reuse is verified with `SELECT CONNECTION_ID(), 42`, not merely by a
successful pool checkout. Fresh-pool replacement requires a changed connection ID.

| Scenario | aiomysql | asyncmy 0.2.16 |
| --- | --- | --- |
| Close an abandoned single-result stream; query again | Same physical connection, correct result | Same physical connection, correct result |
| Close with unread additional results; query again | Correct result | `InternalError: Packet sequence number wrong - got 8 expected 1` |
| Close single-result stream; return to size-one pool; reacquire | Same physical connection, correct result | Same physical connection, correct result |
| Close physical connection with pending results; reacquire from size-one pool | Fresh connection, correct result, no warnings | Fresh connection, correct result, unawaited-coroutine warning |

The protocol failure reproduced in the initial red test, a standalone rerun,
subsequent characterization tests, and final evidence collection. No cancellation
or concurrent connection sharing is needed to reproduce it.

[Raw reports and provenance](results/2026-10-21-asyncmy-lifecycle/) were collected
from clean source commit `53d0a5d`. Tests deliberately **characterize the pinned
candidate's failure**; a green test suite is not a compatibility certification.
The report distinguishes `reused`, `replaced`, and `driver-error`. Exit zero means
the experiment completed and produced a report, not that both drivers passed.
Unexpected non-driver exceptions and operation timeouts still abort collection.

## Source explanation

Inspection of the installed 0.2.16 source and its tagged source:

- [`cursors.pyx`](https://github.com/long2ice/asyncmy/blob/v0.2.16/asyncmy/cursors.pyx):
  `SSCursor.close()` finishes the current result, then loops over `nextset()`.
  `SSCursor.nextset()` opens the following result **unbuffered**. At that point
  its trailing status is not yet known, and the close loop does not explicitly
  finish that new result before checking for another set.
- [`connection.pyx`](https://github.com/long2ice/asyncmy/blob/v0.2.16/asyncmy/connection.pyx):
  `_execute_command()` notices an unfinished unbuffered result, emits
  `Previous unbuffered result was left incomplete`, then calls the asynchronous
  `_finish_unbuffered_query()` **without awaiting it** before sending a new command.
- `MySQLResult.__del__()` also calls that async cleanup method without awaiting it.
  This explains the additional warning on disposal of a pending result even when
  the physical socket has deliberately been closed.

The observed multi-result report includes both the protocol error and
`coroutine 'MySQLResult._finish_unbuffered_query' was never awaited` warnings.
The experiment explicitly collects garbage inside its warning-capture scope so
finalizer diagnostics are retained rather than appearing only at interpreter exit.
It does not suppress the warnings or patch driver internals.

aiomysql's native cursor close is not ideal either: it loads subsequent result
sets. Its close-only tracemalloc peak in this multi-result run was **4,885,091
bytes**. This is scoped Python-allocation evidence, not RSS, a bound, or a general
memory benchmark. No comparable successful asyncmy multi-result close/reuse was
observed, so no memory advantage is claimed for that failing path.

## Why this matters to snekql

`snekql/mariadb/runtime.py::MariaDBCursorAdapter.complete()` deliberately finishes
only the first result and examines its trailing status. If an additional result
exists, it closes the physical connection instead of loading that result and
reusing the socket. The new discard probe demonstrates that a fresh asyncmy
pool connection is usable, but does not implement or certify this whole policy.

A mechanical import substitution is insufficient:

- snekql imports `driver.SSCursor`; asyncmy 0.2.16 exposes it through
  `asyncmy.cursors.SSCursor`, not its package root.
- The aiomysql cursor uses `_connection`; the asyncmy cursor uses `connection`.
  The existing completion/disposal code therefore needs an explicit adapter.
- Cursor cleanup, error classification, warning redaction and pool integration
  must be ported deliberately, not inferred from similar public method names.

Existing public snekql raw-query tests already cover rejection of extra results
and stream completion. **115 tests** in `tests/runtime/test_raw_execution.py` and
`tests/runtime/test_raw_validated_lifecycle.py` pass on the unchanged production
backend. They have not been run through an asyncmy-backed snekql prototype.

## Reproduce

Run from this checkout with MariaDB binaries installed:

```sh
root=$(mktemp -d "$HOME/.cache/snekql-lifecycle-XXXXXXXX")
mkdir "$root/tmp"
for scenario in abandoned-stream multiple-results pool-reuse pool-discard-multiple; do
  TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
    -m benchmarks.asyncmy_lifecycle --scenario "$scenario" \
    >"$root/$scenario.json" || exit
done
```

The essential failing sequence, using an already connected asyncmy connection
with `CLIENT.MULTI_STATEMENTS` enabled and a selected MariaDB database, is:

```python
from asyncmy.cursors import SSCursor

cursor = conn.cursor(SSCursor)
query = "SELECT seq, REPEAT('x', 1024) FROM seq_1_to_4096 ORDER BY seq"
await cursor.execute(query + "; " + query + "; SELECT 99")
await cursor.fetchone()
await cursor.close()
async with conn.cursor() as next_cursor:
    await next_cursor.execute("SELECT CONNECTION_ID(), 42")  # protocol error
```

The sequence tables are MariaDB's built-in sequence engine; no user table or
production database is needed. The runnable harness supplies the owned server,
connection parameters, deadlines, result checks and cleanup missing from this
short excerpt.

## Validation and next steps

- Four new real-driver characterization tests pass, each isolated in a pinned
  uv subprocess. The new scenario commands failed before their implementation.
  When multi-result compatibility failed, that evidence was retained explicitly;
  the test was changed to characterize the failure, not to claim a driver fix.
- 115 related existing runtime tests pass with `PYTHON_CONTEXT_AWARE_WARNINGS=1`.
- `uv run ty check`, `uv run ruff check .`, and `uv run ruff format --check .` pass.
- The full repository suite was **not rerun for this investigation**; changes
  are confined to probes, tests, documentation and recorded evidence.

Upstream issues [#89](https://github.com/long2ice/asyncmy/issues/89) and
[#103](https://github.com/long2ice/asyncmy/issues/103) are closed and discuss prior
cancellation-related desynchronization. Their closure does not establish safety
for this different, non-cancellation reproducer. The non-cancellation reproducer has now been filed upstream as
[asyncmy #165](https://github.com/long2ice/asyncmy/issues/165).

The later prototype continuation evaluates an explicit-drain workaround and
first-result-only adapter completion, then verifies COMMIT faults through public
transactions. Broader adapter validation remains necessary. The native
close path must not become an accidental fallback for additional-result handling.
Cancellation beyond the native asyncio cases below, snekql-level COMMIT integration,
warnings containing server data, TLS,
transactional pool reset, reconnects, maintained MariaDB LTS versions and
cross-platform installation remain untested with asyncmy. At this stage the public snekql prototype seam was deferred; the later
prototype continuation below supplies narrowly scoped integration evidence.


## Continuation: cancellation and rollback — 2026-10-21

The same PR now includes three further public-driver probes:

- `cancel-query`: cancel `execute()` while the server is running `SLEEP(5)`.
- `cancel-fetch`: consume the first streamed row, then cancel the fetch of the
  second row while the server is sleeping.
- `cancel-close`: consume the first streamed row, then cancel cursor close while
  it is draining the sleeping second row.

Each case begins an explicit transaction and inserts primary key 1 into an InnoDB
table before the operation under test. A separate observer connection polls
`information_schema.PROCESSLIST` for that exact connection ID in `User sleep`.
A task-start event plus a pending-task check ensures the operation has entered
and has not already completed when cancellation is issued. There is no arbitrary
client delay used to guess when to cancel. Five seconds is the injected server
stall, not a performance threshold; failure to reach the barrier aborts the probe.

For streaming, a 64 KiB first-row payload makes data available before the second
row enters its sleep. The probe verifies that complete first row before attempting
the second fetch or close. No private driver methods are patched or inspected.

| Observation | aiomysql 0.3.2 | asyncmy 0.2.16 |
| --- | --- | --- |
| `CancelledError` propagated in all three cases | Yes | Yes |
| Driver reports closed before harness defensive close | Yes | Yes |
| Next pool checkout has a different `CONNECTION_ID()` | Yes | Yes |
| Old uncommitted insert is visible | No | No |
| Replacement can insert the same key and read it back | Yes | Yes |
| Deferred cleanup warnings | None | Unawaited cleanup coroutine on fetch/close cancellation |

The driver's closure indicator is measured **before** the harness unconditionally
closes the connection as a safety measure. Consequently this checks the driver
indicator and recovery under an explicit fail-closed application policy, not a
claim that every native-pool failure path is safe without application cleanup.
The replacement insert checks lock release as well as visibility: an uncommitted
row hidden by MVCC alone would not permit immediate successful reuse of the key.
The server may take time to finish its injected sleep and release the old write.
No server `KILL` or explicit `ROLLBACK` assists the normal path.

These are **rollback-before-COMMIT** cases. They provide no evidence that a failed
or cancelled COMMIT did not commit. No command replay occurs. Native
`asyncio.Task.cancel()` is tested; AnyIO repeated cancellation, transport faults,
server restarts and acknowledgement-loss windows remain separate gates.

[Raw reports and provenance](results/2026-10-21-asyncmy-cancellation/) were collected
from clean probe commit `adfb2d7` on CPython 3.15.0 / MariaDB 13.0.2. All six
(driver, scenario) cases recover correctly under the policy above. asyncmy's
unawaited-finalizer warnings remain recorded; they are not a protocol failure in
these cases and are not considered fixed.

Reproduce using the same private `TMPDIR` setup above, replacing the scenario
loop with:

```sh
for scenario in cancel-query cancel-fetch cancel-close; do
  TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
    -m benchmarks.asyncmy_lifecycle --scenario "$scenario" \
    >"$root/$scenario.json" || exit
done
```

Validation for this continuation:

- Three new scenario commands demonstrated red/green cycles; **seven** probe
  characterization tests now pass in total.
- Combined focused run: **178 passed** across the probe tests and existing
  commit-outcome, pool-cancellation-handoff, raw-execution and raw-validation
  lifecycle tests. Existing runtime tests still use the production backend,
  not an asyncmy-backed snekql adapter.
- Type checking, lint, formatting and whitespace checks passed.
- Full repository suite not rerun; no production runtime or dependency changes.

Verdict remains **hold adoption**: the multi-result bug is unresolved, native
cancellation recovery has useful positive evidence, and COMMIT outcome handling
still needs verification through an asyncmy-backed snekql transaction. No merge of `main` was performed for
this continuation, as requested.


## Continuation: COMMIT acknowledgement loss — 2026-10-21

A new single-client loopback packet relay injects faults at the transport boundary.
The driver is unmodified. A separate connection bypasses the relay to create an
InnoDB table and inspect committed data. Each trial begins a transaction, inserts
one row, and calls the driver's public `commit()` method exactly once.

| Relay scenario | Client observation, both drivers | Independent visible rows |
| --- | --- | ---: |
| `commit-control`: forward command and reply normally | `commit()` returns | 1 |
| `commit-drop-before`: receive COMMIT but close both sockets before forwarding it | `OperationalError(2013, ...)` | 0 |
| `commit-drop-ack`: forward COMMIT, receive its successful OK packet, then close without forwarding the reply | `OperationalError(2013, ...)` | 1 |

All cases positively record that the relay received the COMMIT command. The
lost-ack case additionally requires a successful server OK packet; an unrelated
server error is a probe failure, not accepted evidence of a lost commit reply.
The no-fault control confirms that normal COMMIT acknowledgement survives the
relay. There is no retry, replay, mocked `commit()` method or client timing guess.

**The same client error corresponds to opposite persisted outcomes.** This is
expected distributed-transaction uncertainty, not an asyncmy-specific defect.
The harness knows where it injected the fault; an ordinary application does not.
Error 2013 alone therefore cannot justify reporting rollback/rejection or blindly
retrying a write. The existing snekql `unknown` outcome policy must be preserved
by an asyncmy adapter. No new driver-side evidence removes that requirement.

[Raw reports and provenance](results/2026-10-21-asyncmy-commit/) were collected from
clean probe commit `e244243`, on CPython 3.15.0 / MariaDB 13.0.2. Both aiomysql
0.3.2 and asyncmy 0.2.16 produced the table above, with no captured warnings.
These are observations of committed visibility after a transport fault, not tests
of crash recovery, disk durability, replication or failover.

Using the private `TMPDIR` setup above:

```sh
for scenario in commit-control commit-drop-before commit-drop-ack; do
  TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
    -m benchmarks.asyncmy_lifecycle --scenario "$scenario" \
    >"$root/$scenario.json" || exit
done
```

The relay is narrowly scoped to an owned plaintext server, one client and
sequential small text-protocol commands. It does not implement TLS, compression,
prepared statements, pipelining or general proxy behavior. Packets, including
handshake credentials, are forwarded in memory and never logged or persisted.
It closes sockets and joins owned tasks during teardown. The separate observer
runs its checks before the driver's final explicit close, so that cleanup cannot
silently turn an acknowledged transaction into the asserted result.

Validation for this continuation:

- Three new real-driver probe tests demonstrated red/green cycles, bringing the
  lifecycle suite to **ten** tests. Missing relay-interception evidence was also
  exercised as a failing assertion before implementing its report field.
- Combined focused run: **181 passed** (lifecycle probes plus existing
  commit-outcome, pool-cancellation-handoff, raw-execution and raw-validation
  lifecycle tests).
- Type checking, lint, formatting and whitespace checks passed.
- Full repository suite not rerun. Production runtime and dependencies unchanged.

The raw-driver COMMIT ambiguity is now demonstrated rather than hypothetical.
The next integration gate is preserving its classification through the public
snekql transaction API, including cancellation and later cleanup failures. The
multi-result protocol bug remains unresolved; upstream #165 is still open with
no maintainer reply observed during this continuation. `main` was not merged in
this slice.


## Continuation: restricted public-interface prototype — 2026-10-21

The investigation now includes `benchmarks/_asyncmy_adapter.py` and the runnable
`benchmarks.asyncmy_prototype` command. `PrototypeConfig` opts into a separate
runtime through `Database.initialize(config)`. It does not replace imports,
monkeypatch snekql, register a backend or alter production dependencies.

### Cleanup workaround versus adapter policy

The new native `multiple-results-drained` experiment consumes each result with
`fetchmany(128)` until exhausted, then advances with `nextset()`, and finally
closes the cursor. Both drivers subsequently return the correct result on the
same physical connection, without warnings. This is evidence for a **local
explicit-drain workaround**, not a patched or fixed asyncmy release. aiomysql's
`nextset()` can still buffer subsequent results; the fetch batch alone is not a
memory bound on that driver.

Draining every result is **not** snekql's policy: it would consume additional
results that should instead be rejected. The prototype therefore adapts the
existing first-result-only completion boundary to asyncmy's cursor representation.
It finishes the initial unbuffered result, checks trailing `has_next`, and closes
the physical connection if another result exists. It never advances with
`nextset()` in that rejection path. The cursor's native `connection` reference is
detached after disposal rather than using aiomysql's `_connection` name.

This remains a private-protocol dependency (`_result` and
`_finish_unbuffered_query()`), isolated in one experimental cursor adapter.
The asyncmy command fallback and finalizer bugs have **not** been fixed, and
native cancellation probes still retain their earlier finalizer warnings.

### Public transaction observations

The control uses the production aiomysql configuration. The candidate uses
`PrototypeConfig`. All setup, queries, transaction outcomes and committed-row
verification in these cases go through public snekql interfaces; transport-fault
injection uses the same owned relay as before.

| Public-interface case | Both configurations |
| --- | --- |
| Abandon a single-result stream, then query in the same Transaction | Same physical connection, correct result, final outcome `committed` |
| Abandon a stream with another result pending | `RawResultShapeError`, old outcome `not_attempted`, next Transaction gets a different usable connection |
| Normal COMMIT through relay | `committed`, one visible row |
| Drop before COMMIT forwarding | `unknown`, failure category `connection_loss`, code 2013, zero visible rows |
| Drop successful COMMIT acknowledgement | `unknown`, failure category `connection_loss`, code 2013, one visible row |

No Python warnings were captured in these five prototype cases. Expected runtime
logging on discarded connections is not suppressed; it is separate from Python
warning capture and is not a diagnostic-confidentiality certification.

The lost-ack test first failed because the aiomysql-specific classifier did not
recognize asyncmy's exception: the outcome was already `unknown`, but structured
failure metadata was absent. A candidate-specific classifier for the observed
connection-loss code restored that public metadata. This was a real adapter
integration failure caught by the agreed public seam, not a mocked exception.

### Deliberate restrictions

This is **not a complete MariaDB backend port**. The config rejects non-loopback
hosts, TLS, Unix sockets, pools larger than one, active health checks and lifetime/
idle recycling. Its intended scope is owned-server raw-query experiments only.
It reuses snekql's transaction machinery/admission gate and a native asyncmy pool,
but does not port the production owned-pool/TLS implementation.

Only code 2013 has candidate-specific failure classification; other asyncmy
errors currently classify as unknown. Constraint recovery, deadlock/COMMIT
rejection semantics, warning confidentiality, migrations, model/query-builder
execution, cancellation through the public adapter, partial initialization and
shutdown under faults are **not implemented or certified by these tests**.
Inherited aiomysql-specific paths must not be assumed compatible. The cursor's
warning hook is adapted, but its confidentiality behavior still needs tests.

### Reproduce and provenance

```sh
# Use the private $root/tmp setup from the earlier sections.
for scenario in stream extra-results commit-control commit-drop-before commit-drop-ack; do
  TMPDIR="$root/tmp" PYTHON_CONTEXT_AWARE_WARNINGS=1 \
    uv run --locked --with asyncmy==0.2.16 python \
    -m benchmarks.asyncmy_prototype --scenario "$scenario" \
    >"$root/prototype-$scenario.json" || exit
done
TMPDIR="$root/tmp" uv run --locked --with asyncmy==0.2.16 python \
  -m benchmarks.asyncmy_lifecycle --scenario multiple-results-drained \
  >"$root/multiple-results-drained.json"
```

[Raw reports and provenance](results/2026-10-21-asyncmy-prototype/) were collected
from clean merge commit `5f83785`. As requested, `origin/main` at `a10cd17` was
merged into this branch at this checkpoint, bringing in #485 and #486. These
are correctness observations, **not** end-to-end performance measurements of the
combined optimizations and asyncmy.

Post-merge validation:

- **176 passed**: five prototype tests plus existing commit-outcome,
  pool-cancellation-handoff, raw-execution and raw-validation lifecycle tests.
- **25 passed**: eleven native lifecycle probes plus the fourteen regression
  cases from #485/#486. Total: **201 passing focused tests** across disjoint runs.
- New scenarios demonstrated red/green cycles; the missing candidate failure
  classification produced an additional genuine integration regression test.
- Type checking, lint, formatting and whitespace checks passed.
- Full repository suite not rerun. No production driver/dependency switch.

Verdict: **hold adoption, but continue the prototype**. The native cleanup problem
is avoidable in these first-result-only adapter cases, and important COMMIT
semantics survive the public transaction layer. Next gates are exception coverage
and constraint recovery, value/diagnostic fidelity, public-adapter cancellation
and shutdown, TLS/owned-pool behavior, and only then end-to-end performance.
