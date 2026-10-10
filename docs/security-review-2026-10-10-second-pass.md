# Second defensive security review — 2026-10-10

Tracking: maintainer-requested follow-up to #449, #453. This is a source review
and regression record, not a security certification, penetration test, or CVE
assessment. Findings and patches remain local pending the maintainer's disclosure
and publication decision.

## Scope and method

The agreed public boundaries were query factories/compilation, native Database
and Transaction APIs (including streams), configuration/scaffold/migrations, and
representations/tracebacks/logs/warnings/observer events. The review emphasized
unusual failure paths and feature combinations rather than repeating only the
first pass's interpolation checklist.

Reviewed shared runtime ownership and deadline handling, SQLite admission and
background-discard ownership, MariaDB checkout/configuration/TLS adapters,
built-in result decoding, raw result contracts, query composition and quoting,
bounded DDL/check/default rendering, and migration CLI/test-server configuration.
Callbacks and custom renderers remain trusted application code.

Confirmed changes followed failing public behavior regressions before fixes.
One diagnostic test substitutes a controlled timeout at the native aiosqlite
boundary: real server messages cannot reliably produce that combination. This
establishes a redaction gap, not that a particular supported server currently
returns secrets in timeout messages.

## Findings

### Repeated native cancellation could strand transaction cleanup

**Classification:** confirmed lifecycle/availability defect. A real SQLite,
file-backed, single-slot pool reproduction cancelled a task twice at different
cleanup checkpoints. One case stranded the lease: a subsequent Transaction
could not acquire a connection, and Database shutdown also timed out. AnyIO
shields do not block native `asyncio.Task.cancel()`.

Transaction exit now gives native finalization an owned task and joins it even
after repeated caller cancellation. Driver-operation deadlines remain active.
The caller receives cancellation only after cleanup and commit evidence settle.
A competing exit never owns or finishes the first exit's measurement. Nested
ownership is checked against the original caller, not the cleanup worker. Cleanup
returns process-control exceptions to the caller rather than raising them out of
a background Task.

This is not a claim that untrusted SQL alone can trigger the defect. The
availability impact depends on how an application cancels request/worker tasks.
Repeated-cancellation regressions cover real SQLite and MariaDB rollback. Entry
cancellation checkpoint probes also passed without an additional entry fix.

### Builder stream ownership was not enforced consistently

**Classification:** confirmed robustness gap with result-consumption and
availability consequences under documented API misuse. Raw streams rejected
foreign-task access, but builder streams did not. A foreign consumer could take
rows. A foreign exit could close the cursor before native lock release failed.

Both stream kinds now reject foreign-task reads/exits before touching cursor or
lock state. Regressions verify that the owning task can still consume its row
after a rejected call. Exiting a Transaction from its own open stream is rejected
before scheduling cleanup, avoiding a wait for a lock only that caller can free.
This does not introduce application authorization or tenant isolation.

### Native timeout causes could bypass default query redaction

**Classification:** confirmed defensive diagnostic gap at a controlled driver
boundary; no real-server exploit demonstrated. Ordinary builder driver errors
suppressed native causes under the default policy, but the timeout translation
path did not. A driver-originated `TimeoutError` carrying private text survived
in a formatted `DatabaseOperationTimeoutError` traceback.

Builder timeouts now suppress their native cause under `redacted` visibility,
just like other query errors. Explicit `values` visibility retains the unsafe
cause for deliberate diagnostics. Raw diagnostics remain suppressed. This does
not broaden the confidentiality claim to all connection/migration/lifecycle
errors or to traceback tools capturing locals.

### Public temporary-server representations exposed credentials

**Classification:** confirmed accidental disclosure in a test-support API.
`TemporaryMariaDBServer` included its plaintext password in its generated
`str`/`repr`, unlike the main MariaDB Config. Logging the returned server value
could therefore expose caller-supplied or generated test credentials.

The public password field now has `repr=False`. Explicit `.password` access and
credential forwarding remain available. A public-constructor regression failed
before the change and passes afterward. This finding concerns the test helper;
it does not establish that production Config representations leaked passwords.

## Additional checks without new defects

- A native corpus passes quote/backtick, comment, semicolon, percent-placeholder,
  control-character, and Unicode output labels through UNION ALL, CTE output
  references, filtering, and ordering on both backends. Expected row values and
  multiplicity are asserted, rather than treating a server error as safety.
- CTE source names retain their existing restricted identifier grammar; output
  labels use the separate quoting path. The corpus does not weaken that grammar.
- Existing native transaction-policy, commit-outcome, telemetry-context and
  competing-exit regressions pass with owned cleanup.
- Source review found no additional SQL injection or TLS downgrade in the
  examined built-in paths. This is an observation within the stated scope, not
  proof of absence throughout the package or its dependencies.

## Compatibility and operational implications

- Cancellation during exit no longer abandons native finalization. It can wait
  for cleanup deadlines; an acknowledged COMMIT remains committed. Cancellation
  is never a guarantee that a write was rolled back, and no write is replayed.
- Builder stream handoff between tasks is now rejected with a package error;
  this was already forbidden by the documented usage contract.
- Default timeout exception chaining is reduced. Portable failure/timeout
  information remains available; unsafe `values` visibility remains explicit.
- Workload sizes, application authorization, verified transport policy, database
  privileges, and trusted raw SQL/migration bodies remain caller-owned.

## Validation

The host has no MariaDB server executable. Native validation uses a disposable
Ubuntu 24.04 container with MariaDB 10.11.14, a separate source copy and separate
server data. The locked project environment and Python 3.15.0 are used with
`PYTHON_CONTEXT_AWARE_WARNINGS=1`; SQLite is 3.53.1. No project dependencies or
host system packages were changed, and existing host test databases were not
removed or reused. This run does not certify the other supported MariaDB series.

An initial full-suite attempt exposed missing `git` in the minimal container,
which broke benchmark provenance subprocesses. A typing-report probe also needed
repository metadata in the separate copy. Git and that metadata were added inside
the container only. That setup attempt finished with 41 failures, one error, and
3,771 passes; it is not presented as successful full-suite validation. The
metadata-dependent probe passed on rerun.

The complete suite was then rerun on the final source and tests. SHA-256 hashes
of both changed Python implementation files and all four affected test files
matched the host checkout before accepting the results.

| Check | Result |
| --- | --- |
| `uv run snektest tests` (isolated native container) | **3,826 passed**, exit 0, 878.10 seconds |
| `uv run ty check` (host) | Passed |
| `uv run ruff check .` (host) | Passed |
| `uv run ruff format --check .` (host) | Passed |
| `uv run python scripts/generate_query_overloads.py --check` (host) | Passed |
| `git diff --check` (host) | Passed |

The 43 added cases comprise 28 lifecycle/cancellation/stream/control-flow cases,
12 native composition cases, two timeout visibility cases, and one public
credential-representation case. Expected existing MariaDB baseline-adoption
warnings appeared in the full run; no test failed.

## Remaining assurance limits

This review did not fuzz every native response or malformed legacy row, perform
an adversarial network/protocol assessment, audit dependency implementations, or
validate an employer's authorization, schema, privileges, deployment and logging
configuration. Cancellation schedules are a finite regression corpus, not an
exhaustive scheduler proof. Python 3.15.0 and one MariaDB series were exercised
locally; the remaining supported targets still need normal CI/release coverage.

For workplace adoption, use a reviewed, merged and released hardened version;
retain verified transport, least-privilege credentials, safe logging defaults,
explicit deadlines and the supported-version upgrade policy. These tests do not
turn raw SQL into a sandbox or certify the surrounding application.
