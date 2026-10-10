# Third defensive security review — 2026-10-10

Tracking: maintainer-requested follow-up to #449 and #453, #455. This is a
bounded source review and regression record, not a security certification or
CVE assessment.

## Scope and method

The maintainer confirmed native Database and Transaction APIs (including
streams), public initialization/migration/verification/shutdown APIs, and
formatted tracebacks/representations/logs/warnings/observer events as the test
seams. The review prioritized malformed stored values and cleanup paths outside
Transaction exit rather than repeating the first pass's SQL interpolation
corpus.

Reviewed built-in column and temporal decoding, scalar/table/stream
Materialization, SQLite migration apply/history inspection and final connection
return, MariaDB migration-lock disposition, partial connection initialization,
and the existing owned pool shutdown paths. Trusted Python callbacks, raw SQL
intent, application authorization and workload limits remain caller-owned.

Each fix followed a failing public-boundary test. Native MariaDB supplies the
malformed stored-value reproduction without substituting driver results. The
SQLite cancellation reproduction uses real file-backed storage and a single
pool slot, with controlled pauses at the external aiosqlite execute/rollback
boundary. It does not establish that every scheduler interleaving or arbitrary
untrusted SQL triggers the defect.

## Findings

### Legacy MariaDB timestamp parser causes bypassed safe model diagnostics

**Classification:** confirmed defensive diagnostic disclosure on a mismatched
legacy schema. A model declaring native DateTime storage can read text from an
existing TEXT column before schema verification. Rejecting malformed timestamp
text produced a sanitized ModelValidationError, but its chained standard-library
parser error included the stored text in an ordinary formatted traceback.

The built-in timestamp codec now suppresses that parser cause while retaining
the package error and column context. Regression cases cover scalar projections,
Row Model materialization, and chunk streams, with both validation settings.
Native temporal wire conversion still happens when `validate=False`; that
option does not turn native DATETIME decoding into an untyped raw result API.

This is not a claim that valid DATETIME storage accepts arbitrary secret text,
that schema verification approves the mismatched column, or that all application
callbacks and third-party diagnostics are confidential. No SQL injection or
cross-tenant access exploit was demonstrated.

### Repeated cancellation could abandon SQLite migration connection cleanup

**Classification:** confirmed lifecycle/availability defect at controlled
native-driver checkpoints. Repeated native task cancellation interrupted
migration rollback and then the runtime's final rollback/return path. A later
Transaction timed out acquiring the sole slot; Database shutdown timed out too.
AnyIO cancellation shields alone do not stop `asyncio.Task.cancel()`.

The runtime's final migration connection cleanup now runs in an owned task and
joins it despite repeated caller cancellation. It finishes rollback and selects
return or discard before propagating cancellation. Unknown authorizer or
transaction disposition still prevents reuse; detached physical discard remains
owned by the pool and retains capacity until close completes. Process-control
exceptions are returned to the caller instead of raised out of the cleanup task.

Three regression cases exercise `migrate()`, `verify_migrations()`, and
`migration_status()`. The apply case performs a write before the controlled
pause; a subsequent public Transaction confirms that its uncommitted row did
not escape cleanup. The same fixture closes the Database normally after each
case.

No migration is replayed, no acknowledged commit is undone, and no new timeout
or transactional-DDL guarantee is introduced. Cancellation can wait for final
cleanup, just as it already does for owned Transaction finalization.

## Additional review observations

- Existing SQLite acquisition-deadline regressions cover paused connectivity and
  settings probes, native opening cancellation, and capacity retention through
  detached physical close. They pass with this change.
- Both backend pools already retain owned shutdown tasks when a close waiter is
  cancelled. This pass does not replace that design or claim exhaustive startup
  or shutdown cancellation coverage.
- MariaDB migration lock release retains a positive-release check and fails
  closed on uncertain disposition. No corresponding MariaDB migration change
  was justified by the reproductions in this pass.
- Existing redacted Pydantic primitive/JSON validation and bounded derived-value
  decoding remain in place. The confirmed timestamp issue was a parser path
  before logical validation, not a reason to suppress trusted callback failures
  indiscriminately.

## Validation

Native validation used an isolated Ubuntu 24.04 container, a separate source
copy and separate server data, Python 3.15.0, SQLite 3.53.1 and MariaDB 10.11.14.
The locked project environment was used with
`PYTHON_CONTEXT_AWARE_WARNINGS=1`. No project dependency or host system-package
changes were made. The review-owned container was stopped after validation.

The first fixture setup attempts failed because MariaDB refuses to run as root
and a non-root process could not write the mounted checkout's retained data
directory. Validation moved to the separate writable copy before accepting any
native regression result. A host adjacent-test invocation also selected MariaDB
cases despite missing native executables: it finished with 39 fixture errors and
48 passes. That is not successful validation; SQLite-only host coverage was
rerun separately, and the complete native suite ran in the container.

| Check | Result |
| --- | --- |
| Locked-environment `python -m snektest tests` (native container) | **3,835 passed**, exit 0, 901.05 seconds |
| Both new regression modules rerun on final files (native container) | **9 passed**, exit 0, 1.81 seconds |
| SQLite migration recovery and acquisition-deadline modules (host) | **7 passed** |
| `uv run ty check` | Passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run python scripts/generate_query_overloads.py --check` | Passed |
| `git diff --check` | Passed |

During the full run, the migration regression was strengthened to perform a
write before cancellation; a test annotation/lint clarification and cleanup
worker docstring were also finalized. No implementation behavior changed after
the full-suite snapshot. Both regression modules were then rerun on the final
source and assertions. SHA-256 hashes of both changed implementation files and
both new test modules matched the host checkout for that rerun. The nine added
cases comprise six legacy timestamp diagnostic cases and three migration
cleanup cases. Expected existing MariaDB baseline-adoption warnings appeared;
no full-suite test failed.

## Remaining assurance limits

The tests cover finite schedules and payloads, not an exhaustive concurrency
proof or fuzzing of every native response. The legacy timestamp case deliberately
uses a schema mismatch; callers should still verify live schemas and migrate
legacy data. Other supported MariaDB series require normal CI/release coverage.
No dependency implementations, adversarial network/protocol behavior,
application authorization, database privilege configuration, or logging
infrastructure were audited. Raw SQL and migrations remain trusted application
code, not sandboxed programs.
