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
for this different, non-cancellation reproducer. No new upstream issue has been
filed as part of this investigation.

Recommended next step: submit the small reproducer upstream and evaluate a fix,
then build the isolated snekql adapter with fail-closed completion. The native
close path must not become an accidental fallback for additional-result handling.
Cancellation, transaction outcomes, warnings containing server data, TLS,
transactional pool reset, reconnects, maintained MariaDB LTS versions and
cross-platform installation remain untested with asyncmy. The public snekql
prototype seam is explicitly deferred, not considered passed by these probes.
