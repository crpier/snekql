# Error handling guide

Expected errors raised by snekql inherit from `SnekqlError`. Catch that at an
application boundary, or a more specific exception when you know how to handle
it. Do not catch every Python exception just to label it a database failure.

If a write failed, start with [commit outcomes](#commit-outcomes) before retrying.
For ordinary use, read [transactions](transactions.md) first. This page covers
what can go wrong and which recovery actions are safe.

```python
from snekql.sqlite import SnekqlError

try:
    async with db.transaction() as tx:
        await tx.execute(statement)
except SnekqlError as error:
    handle_database_failure(error)
```

## Error groups

Logical type errors:

- `ZonedDatetimeError`: `ZonedDatetime` received a naive datetime or a timezone
  implementation without a stable persistence identity. Use an IANA
  `zoneinfo.ZoneInfo` or fixed-offset `datetime.timezone`.

Model errors:

- `ModelDeclarationError`: invalid table model class or column declaration.
- `ModelValidationError`: invalid pending or fetched model value.
- `FrozenModelError`: attempt to mutate an immutable model instance or finalized
  column metadata.

Query errors:

- `QueryConstructionError`: invalid builder method call, such as
  `where()` with no predicates, passing a single-value select to
  `fetch_one_or_none` (whose `None` would be ambiguous), or calling
  `fetch_chunks(..., size=N)` with a non-positive `size`.
- `QueryCompilationError`: a built query cannot compile to valid backend SQL.
  Typed Query Runtime calls reject guaranteed-incomplete queries statically, but
  the error remains the runtime backstop for `Any`, casts, untyped callers, and
  forged state—for example, a select without `.where(...)` or `.all()`.

Runtime errors:

- `DatabaseClosedError`: work was requested after a successful close.
- `DatabaseClosingError`: new work was requested while close is in progress.
- `DatabaseCloseTimeoutError`: close timed out waiting for checked-out work.
- `DatabaseOperationTimeoutError`: transaction begin, query I/O, commit, rollback,
  or cursor cleanup exceeded its operation deadline. `.operation` and `.timeout`
  identify the failed phase and budget.
- `PoolTimeoutError`: no connection became available before acquisition timeout.
- `TransactionStateError`: base for transaction lifecycle misuse; catch it to
  treat every off-path use of a transaction uniformly (see [Transaction
  lifecycle contract](#transaction-lifecycle-contract)).
  - `TransactionClosedError`: a transaction was used after it closed.
  - `TransactionNotStartedError`: a query ran before the transaction was entered.
  - `TransactionReuseError`: a transaction was entered more than once.
- `ResultCardinalityError`: database output violated an Execution Plan's row
  contract, including a single-row `RETURNING` statement that produced no row.
  - `NoResultError`: `fetch_one` found no row for its exactly-one contract.
  - `MultipleResultsError`: `fetch_one`/`fetch_one_or_none` matched more than one
    row.
- `ExecutionError`: backend execution failed and parameterized query context is
  available. String telemetry redacts bound values by default.

Schema errors:

- `SchemaVerificationError`: strict model verification found Schema Drift after
  inspecting every requested table. Instances expose the immutable
  `SchemaVerificationResult` as `.result`.

Migration errors:

- `MigrationDeclarationError`: the declaration is not an exact ordered
  `dict[str, str]`, contains invalid names or bodies, or uses a backend-invalid
  body. Validation happens before connection acquisition.
- `MigrationHistoryError`: recorded history is missing, malformed, divergent,
  behind the declaration during read-only verification, or still uses legacy
  history without explicit adoption.
- `MigrationError`: a hand-authored migration body failed to apply. The message
  names the failing migration; previously-applied migrations stay recorded so a
  fixed retry resumes from the failure point (see [migrations.md](migrations.md)).
- `MigrationLockError`: migration lock ownership or release could not be
  confirmed. MariaDB discards an unsafe physical connection rather than
  returning it to the pool.
- `MigrationLockTimeoutError`: SQLite's writer lock or MariaDB's advisory lock
  could not be acquired within its budget. It is a
  `MigrationLockError` subclass. The losing instance applied nothing; a retry
  after the holder finishes checks the exact prefix and applies the pending
  suffix.

## Classified transaction failures

`DatabaseRuntimeError.failure` is an optional frozen `DatabaseFailure`. Both
backend namespaces export it and the `FailureCategory` literal type. Transaction
acquisition, query execution, stream IO, and transaction control attach native
evidence when available. Existing exception types remain catchable.

```python
from snekql.mariadb import DatabaseRuntimeError

try:
    async with db.transaction() as tx:
        await tx.execute(statement)
except DatabaseRuntimeError as error:
    failure = error.failure
    if failure is not None and failure.category == "unique_violation":
        report_duplicate()
    else:
        raise
```

The metadata fields are `backend`, `category`, `code`, `sqlstate`, and
`constraint`. `code` is the native integer error code, including SQLite extended
codes. SQLSTATE and constraint names remain `None` when the driver does not
supply structured fields. Error messages are never parsed to guess missing
metadata. For example, a constraint name present only inside a MariaDB message
is not extracted. SQLSTATE and constraint names are omitted from the metadata's
representation; deliberate attribute access still exposes them.

| Category | Evidence examples |
| --- | --- |
| `unique_violation` | SQLite primary-key/unique/rowid codes; MariaDB 1062 |
| `foreign_key_violation` | SQLite foreign-key code; MariaDB 1451/1452 |
| `check_violation` | SQLite CHECK code; MariaDB 4025 |
| `not_null_violation` | SQLite NOT NULL code; MariaDB 1048 |
| `deadlock` | MariaDB 1213, even though its SQLSTATE is 40001 |
| `serialization_conflict` | SQLite BUSY_SNAPSHOT; MariaDB SQLSTATE 40001 without a more specific known code |
| `lock_conflict` | Other SQLite BUSY/LOCKED codes; MariaDB 1205, including NOWAIT |
| `connection_loss` | MariaDB 1927/2006/2013/2055 or a valid connection-exception SQLSTATE |
| `unknown` | A recognized driver exception without a supported category |

`failure is None` means no classified driver evidence accompanies the error.
Lifecycle misuse, result-contract errors, and application operation deadlines
do not invent a driver code. `unknown` differs from `None`: the driver is known,
but its evidence does not establish a supported category. SQLite storage IO
errors are not mislabeled as network connection loss.

Classification does **not** authorize statement retries or connection reuse.
The same unique violation can be recoverable inside a savepoint, terminate an
entire SQLite transaction under `OR ROLLBACK`, or arrive after uncertain stream
IO. The existing recovery checks still decide safety. There are no automatic
statement retries. Handle a terminal failure outside the Transaction context.

Raw failures retain metadata without exposing SQL, parameters, or driver messages
in ordinary exception formatting. Typed errors retain their existing deliberate
SQL/parameter inspection and chained driver cause. Library transaction-control
logs no longer include driver exception text. Application logging of explicit
causes, metadata attributes, or parameter values remains an explicit disclosure.

## Commit outcomes

Both namespaces export `CommitOutcome`. Retain a Transaction reference when you
need its read-only `commit_outcome` after an exception or cancellation:

```python
transaction = db.transaction()
try:
    async with transaction:
        await transaction.execute(statement)
finally:
    record_commit_outcome(transaction.commit_outcome)
```

Inspect the outcome **after context exit has completed or raised**, not while
another task is still closing the Transaction.

| Outcome | Meaning |
| --- | --- |
| `not_attempted` | The managed outer COMMIT was never attempted. Normal rollback, failed entry, and discarding an unsafe transaction leave this value. |
| `rejected` | Specific backend evidence proves that the managed COMMIT failed without committing. |
| `committed` | The driver acknowledged COMMIT, even if later cleanup failed. |
| `unknown` | COMMIT was attempted but neither acknowledgement nor proven rejection reached the runtime. |

`rejected` currently includes SQLite BUSY or deferred foreign-key errors while
the native connection remains in its transaction, and MariaDB's InnoDB deadlock
response. A generic error or serialization SQLSTATE alone does not prove COMMIT
rejection. Lost acknowledgements, deadlines, and cancellation before an observed
acknowledgement remain `unknown`.

A SQLite cursor-close or policy-restoration failure **after acknowledgement**
leaves `committed`, including restoration timeout or cancellation. Such failures
still discard the connection. Outcome evidence does not make it reusable.
Cancellation and existing timeout/error types retain their meaning.

This property describes the library's managed outer COMMIT only. It does not
track raw COMMIT statements, implicit commits from MariaDB DDL, nontransactional
tables, stored-program side effects, or external services. `not_attempted` is not
a blanket claim that no side effect became durable. Savepoint release does not
change the outer commit outcome. Acknowledgement is not itself a power-loss
guarantee; see [SQLite durability policy](engine-settings.md#sqlite-durability-policy).

## Whole-transaction retries

Retries are an application decision. The library does not retry failed query
statements. Existing SQLite `BEGIN IMMEDIATE` writer-lock acquisition retries
remain separate and happen before application transaction work starts.

The executable [retry example](../examples/transaction_retry.py) repeats an entire
SQLite callback, including its reads, in a **fresh Transaction**. MariaDB can use
the same loop with its namespace's annotations. It permits at most three attempts
and full-jitter exponential waits bounded by 0.05 and 0.10 seconds. Acquisition
and operation deadlines still apply independently; the attempt limit is not an
overall wall-clock deadline.

The example retries only deadlocks and serialization conflicts, and only after
`not_attempted` or `rejected` outcomes. It propagates other errors, exhausted
attempts, and cancellation. It refuses to report success if the callback swallowed
a terminal error and the Transaction exited without committing. Recoverable
optional writes belong in explicit savepoint contexts instead.

Before applying this pattern:

- Use transactional tables and avoid raw transaction control or implicit commits.
- Give each logical operation a durable idempotency key reused across attempts.
  Store the key and database effects atomically. Do not generate a new key per try.
- Keep emails, payments, HTTP calls, and other external effects out of the retried
  callback, or use the destination's own durable idempotency contract. An outbox
  row in the same transaction can defer delivery until after commit.
- Handle unique, foreign-key, CHECK, and NOT NULL failures as application conflicts,
  not a generic retry queue. Lock conflicts can have persistent causes too.
- Never replay an acknowledged commit because its cleanup failed.
- Reconcile `unknown` using the logical operation's key against the authoritative
  database. A missing row alone is not proof of failure while the old operation
  may still be in flight. A safe resubmission must reuse an atomic idempotency
  claim so it cannot apply the effect twice. There is no universal reconciliation
  algorithm for arbitrary callbacks.

The example rethrows unknown and committed-close failures. Adapt that branch to
record or reconcile the application's request ID; do not broaden its category
filter and accidentally retry ambiguous commits.

## Warnings

Alongside the exception hierarchy, snekql raises advisory warnings for
declarations that are legal but likely wrong. Every intentional
package-originated warning is a `SnekqlWarning` subclass, re-exported from each
backend namespace, so applications can filter the whole group by category:

```python
import warnings
from snekql.sqlite import SnekqlWarning

warnings.filterwarnings("ignore", category=SnekqlWarning)
```

- `LexicalDatetimeWarning`: a SQLite `Text()` column carries a datetime logical
  type without an order-preserving wire form (bare `datetime` and pydantic
  `AwareDatetime` both qualify), so SQL `=`, `ORDER BY`, and range predicates
  compare the stored text lexically rather than by instant. The warning fires
  once per offending column at **model declaration time**, not first encode, and
  keys on the absence of the public `OrderPreserving` marker. Annotate the column
  with `UtcDatetime` (which carries the marker) to silence it and get
  instant-correct comparisons; see
  [ADR 0009](adr/0009-utcdatetime-curated-logical-type.md).
- `LexicalDecimalWarning`: a `Text()` column on either backend carries a
  `decimal.Decimal` logical type without a canonical wire form. SQL equality,
  `IN`, and unique indexes can miss because the same decimal value can serialize
  as different text, and ordering remains lexical. Use `CanonicalDecimal` for
  equality-safe text storage, integer minor units for SQLite ordering and
  aggregation, or MariaDB native `Decimal(precision, scale)` when that backend is
  available.
- `LexicalDurationWarning`: a `Text()` column on either backend carries a
  `datetime.timedelta` logical type without a text-order-preserving wire form.
  The wire form is signed integer total milliseconds, so stored as text it sorts
  lexically — `"10000"` sorts before `"9000"` though it is the longer duration,
  and negative durations sort wrong — making SQL `=`, `ORDER BY`, and range
  predicates disagree with elapsed-time order. `Duration` shares this integer
  wire form, so it warns over `Text()` too: store durations over `Integer()`,
  where integer order equals duration order.

## Transaction lifecycle contract

A `Transaction` is **single-use and not re-entrant**. Enter it exactly once with
`async with db.transaction()`, run queries while it is open, and let the block
exit close it — committing on a clean exit and rolling back if the block raises.
Each `db.transaction()` call returns a fresh transaction; reuse a closed one and
you get an error, not a silent no-op.

```python
async with db.transaction() as tx:
    await tx.execute(insert(user))
    rows = await tx.fetch_all(select(User).all())
# committed here; `tx` is now closed and must not be touched again
```

Off-path use is deliberate and tested (see
`tests/sqlite/test_transaction_misuse.py`):

- **Query before entering** → `TransactionNotStartedError`. Calling
  `execute` / `fetch_*` / `fetch_chunks` on a transaction you have not entered
  with `async with` is rejected.
- **Query after closing** → `TransactionClosedError`. The transaction released
  its connection on exit; reach for a new `db.transaction()`.
- **Entering twice** → `TransactionReuseError`, including while the first caller
  is acquiring a connection or running `BEGIN`, while it is open (`already in
  progress`), or after it has been used and closed. A competing entry is rejected
  immediately rather than queued as another physical transaction. If pool
  acquisition itself fails or is cancelled, its entry reservation is released
  and the same object may retry acquisition. Failure during `BEGIN` retains the
  existing terminal failure behavior; a successfully used transaction cannot be
  restarted.
- **Closing twice** → `TransactionClosedError`. The first exit already
  committed or rolled back; a second `__aexit__` has nothing left to close.
- **Sharing one transaction across concurrent tasks** is *safe but serialized*.
  All queries on a single transaction run on one connection guarded by an
  internal lock, so concurrent callers take turns rather than corrupting the
  connection. Close waits behind any in-flight query (see
  `shared_transaction_close_waits_for_active_query` in
  `tests/runtime/test_async_lifecycle.py`). Sharing buys no parallelism — open
  separate transactions for concurrent database work.
- **Nesting transactions from one `Database`** does not create a savepoint.
  Each `db.transaction()` checks out its own pooled connection and commits
  independently; a transaction opened inside another's block is unrelated to it.
  With only one connection available the inner open simply waits for a
  connection and times out with `PoolTimeoutError` — it does not nest.

## Transaction isolation and access mode

Transaction policies are explicit and apply to one outer Transaction:

```python
async with db.transaction(isolation="serializable", read_only=True) as tx:
    rows = await tx.fetch_all(query)
```

Both namespaces export `IsolationLevel` for helper annotations. Supported levels
are `"read_uncommitted"`, `"read_committed"`, `"repeatable_read"`, and
`"serializable"` on MariaDB. SQLite accepts only `"serializable"`; requesting
another level raises `DatabaseRuntimeError` before connection acquisition.
SQLite also rejects `read_only=True` combined with `mode="immediate"`, which
requests a writer reservation. The existing MariaDB `mode` behavior is unchanged.

`isolation=None` and `read_only=None` preserve existing backend/connection defaults.
`read_only=False` explicitly requests read-write access, even if the inherited
default is read-only. Neither isolation nor read-only options can be changed by
`begin_nested()`; savepoints inherit the outer Transaction's policy.

MariaDB applies next-transaction characteristics before BEGIN rather than changing
session defaults. SQLite temporarily sets `query_only` for access mode and disables
`read_uncommitted` for explicit serializable isolation. Commit or rollback restores
the actual previous SQLite settings before the connection returns to the pool.
Ordinary transactions with no explicit options do not change these settings.

The existing begin deadline covers policy setup and BEGIN. Commit/rollback
deadlines include SQLite policy restoration. Interrupted setup or failed restoration
causes connection discard, not reuse with uncertain settings. Cancellation between
driver calls follows ordinary shielded rollback and restoration rules.

**A restoration failure may occur after the database has committed.** A runtime
error from transaction exit is not proof that the writes rolled back. Do not retry
non-idempotent writes blindly. During an existing application failure, restoration
errors do not replace that failure, and the connection is still discarded.

Read-only is a database policy, not a security sandbox. It covers ordinary builder
and raw writes, but backend-specific exceptions remain, such as MariaDB temporary
table operations. Do not use arbitrary raw SQL to change session settings,
autocommit, transaction boundaries, or SQLite PRAGMAs inside managed transactions.
The runtime does not parse raw SQL to prevent callers from overriding policy.

Isolation also retains engine-specific semantics. InnoDB read-committed reads see
later commits, repeatable-read reads retain their consistent snapshot, and
serializable reads can block conflicting writes. SQLite serializable isolation
does not add row locks or concurrent writers. Application deadlines and explicit
transaction retry decisions remain necessary under contention.

## Locking SELECTs

MariaDB supports explicit row locking on a completed single-table SELECT:

```python
claim = (
    mariadb.select(Job)
    .where(Job.id.gt(0), Job.status.eq("pending"))
    .order_by(Job.id.asc())
    .limit(1)
    .for_update(wait="skip_locked")
)

async with database.transaction(isolation="read_committed") as tx:
    job = await tx.fetch_one_or_none(claim)
    if job is not None:
        await tx.execute(
            mariadb.update(Job).where(Job.id.eq(job.id)).set(Job.status.to("claimed"))
        )
```

The fetch and claim update belong in the same Transaction. Committing the fetch
before updating loses its lock protection. This is an atomic claim example, not
an exactly-once processing system; lease expiry and crash recovery remain
application concerns.

`for_update()` defaults to `wait="block"`. Other choices are `"nowait"`, which
reports a conflicting row lock as `ExecutionError`, and `"skip_locked"`, which
omits locked rows. A skipped result can be empty. These options do not eliminate
network, metadata, or other resource waits; operation deadlines still apply.
NOWAIT errors remain terminal under the current failure policy. Start a new
Transaction for a subsequent attempt rather than continuing after that error.

Locking modifiers preserve backend identity, result contracts, parameter order,
and readiness. They do not replace `where()` or `all()`. Model, scalar, tuple,
named, and single-table alias projections are supported. Reapplying the modifier
replaces its wait choice without mutating the original query.

SQLite rejects locking clauses during compilation. There is no emulation using
`BEGIN IMMEDIATE`: that requests SQLite write intent, not row-level locking.
Joins, DISTINCT, GROUP BY/HAVING, aggregate projections/orderings, and locking
SELECTs embedded as subqueries are also rejected during compilation. A lock on
an outer query does not add locking clauses to its ordinary subqueries.

The runtime rejects locking SELECTs in read-only transactions before driver IO,
including inherited read-only defaults and streaming. Rejection does not poison
the Transaction. The check uses the server's active transaction status rather
than assuming its session default or the caller's requested options are current.
Raw SQL is not parsed and still relies on server enforcement.

Locks belong to the outer Transaction. Finishing a fetch, closing a stream, or
successfully releasing a savepoint does not commit or release its row locks.
Do not rely on rolling back a savepoint to release all InnoDB locks either.
Choose indexes deliberately: InnoDB may lock scanned records or index ranges
beyond the rows ultimately returned. SKIP LOCKED does not promise fairness or a
complete, consistent snapshot. These guarantees require transactional tables,
such as InnoDB; nontransactional storage engines are not a portable substitute.

**EXPLAIN is not a lock-free inspection method.** MariaDB can lock a row while
optimizing an EXPLAIN of a locking SELECT, even without executing its writes.
Both `explain()` and `explain_analyze()` therefore require a read-write Transaction
for these queries. ANALYZE executes the query and acquires its native locks.
Neither method adds automatic rollback. Use `.compile()` for inspection without
connection acquisition or database IO.

## Explicit nested transactions

Use `tx.begin_nested()` to create a savepoint on an already-open Transaction:

```python
async with db.transaction() as tx:
    await tx.execute(first_write)
    try:
        async with tx.begin_nested():
            await tx.execute(optional_write)
            check_business_rules()
    except RejectedOperation:
        pass
    await tx.execute(final_write)
```

`RejectedOperation` and `check_business_rules` are application-defined. Catch the
exception **outside** the nested context: exceptional exit rolls back its writes,
releases the savepoint, and propagates the exception. Catching an application
exception inside the block makes its exit successful instead.

Successful nested exit releases the savepoint, not a commit. The outer
Transaction remains responsible for committing all retained work or rolling it
all back. Further `begin_nested()` calls create deeper savepoints on the same
connection, so nesting works with `pool_size=1`. It does not acquire a connection,
flush Python objects, or return a new Transaction. Keep executing through `tx`.
Nested `db.transaction()` calls retain their independent-connection behavior.

The contexts have generated private names, are single-use, and must exit in
reverse entry order. Misuse raises `TransactionStateError` or its existing
lifecycle subclasses. An outer Transaction closed with unfinished nested
contexts discards its connection rather than committing their work.

### Ownership and streams

While a nested context is active, only the task that entered it may query, open
another nested context, or close the Transaction. Other tasks receive
`TransactionStateError`; they do not wait to join the savepoint's work. Outside
nested contexts, ordinary Transaction queries remain serialized across tasks.

Streams can be opened and consumed inside a nested context by its owner. Close
them before entering or exiting a savepoint. Crossing a savepoint boundary with
an open stream raises `TransactionStateError` rather than waiting on the stream's
lock. Builder and raw streams both respect savepoint ownership.

### Recovery limits

Application exceptions, including materialization/validation errors after driver
completion, can roll back nested work without losing earlier outer writes.
Cancellation between driver calls also unwinds the nested context with shielded
cleanup. Cancellation still propagates; this is not automatic cancellation
suppression or a retry policy.

Recognized immediate constraint failures can recover at savepoint exit. The
supported cases are primary/unique keys, NOT NULL, CHECK, and foreign keys,
reported during statement execution with completed driver cleanup. Catch the
existing `ExecutionError` outside the nested block:

```python
async with db.transaction() as tx:
    await tx.execute(first_write)
    try:
        async with tx.begin_nested():
            await tx.execute(possibly_conflicting_write)
    except ExecutionError:
        # Further queries succeed only if savepoint rollback/release succeeded.
        pass
    await tx.execute(final_write)
```

After a recognized failure, the nested scope is rollback-required. Queries,
streams, and further nested entry are blocked until that scope exits. Catching
the `ExecutionError` inside the block does not allow more work: clean exit then
rolls back the scope and raises `TransactionStateError` rather than silently
releasing partial writes. Successful rollback and release restore only the
innermost scope's enclosing transaction, without clearing any unsafe-connection
flag. The exception type alone never proves recovery succeeded.

Timeouts, cancellation during driver IO, unknown driver errors, and failed
savepoint control/cleanup remain terminal. So do whole-transaction rollbacks,
such as MariaDB deadlocks or SQLite `ON CONFLICT ROLLBACK`, and constraint errors
encountered later while fetching or closing a cursor. MariaDB streaming INSERT
RETURNING can report a constraint failure after returning column metadata; those
late failures remain terminal. Catching an error cannot revive these connections.

Constraints checked only at outer commit, such as deferred SQLite foreign keys,
are outside the savepoint's recovery window. Savepoints also do not introduce
retries or change ordinary driver-error handling outside a nested context.

Savepoint control and cursor cleanup use the existing per-operation deadline.
Failed cleanup preserves a pending application exception and logs a redacted
failure; failed release on a clean exit raises a runtime error. None of these
failures permits the outer Transaction to commit the unsafe connection.

Use transactional tables, such as InnoDB on MariaDB. Do not issue raw transaction
control, change autocommit, manipulate the private savepoints, or execute
implicitly committing DDL inside these contexts. Savepoints cannot undo external
side effects or nontransactional writes, and raw SQL is not parsed to enforce
these restrictions.

## Transaction operation deadlines

Both Backend Configs default `operation_timeout` to 30 seconds. With no override,
connection acquisition uses `acquire_timeout`, while transaction begin, each
query operation, stream open/fetch/close, commit, and rollback each receive a
fresh `operation_timeout` budget. The timer does not include application code
between database calls and is not one deadline for the transaction's total
lifetime.

Pool acquisition uses one deadline for queueing, lazy connection checkout/opening
and first-use connection settings. Configuration does not get a fresh budget
after checkout. Expiry raises `PoolTimeoutError`, not an operation timeout.
SQLite retains its immediate idle-connection fast path, including a zero
acquisition budget; opening a new connection requires time in the budget.

When SQLite opening times out or is cancelled, cleanup runs in a tracked task so
waiting for its worker thread cannot hold the caller past the acquisition
deadline. That pool slot remains occupied until cleanup finishes; another
acquisition can therefore time out rather than exceed `pool_size`. Database close
also waits for these opening/cleanup tasks through the admission count. MariaDB
closes an unsuccessfully configured socket before releasing its slot.

`db.transaction(timeout=N)` overrides **both** budgets for that transaction:
connection acquisition and every driver operation use `N`. This makes one call
site sufficient for short jobs while keeping pool and operation defaults
independently configurable.

A timed-out query or transaction-control call leaves physical connection state
uncertain ([ADR 0017](adr/0017-per-operation-deadlines-fail-closed.md)). The
Transaction becomes unusable and discards that connection instead
of returning it to the pool. A commit timeout raises
`DatabaseOperationTimeoutError`. An outcome of `unknown` requires reconciliation
using the logical operation's durable idempotency key. A timeout during cleanup
after acknowledgement leaves `commit_outcome == "committed"`; do not replay it.
See [commit outcomes](#commit-outcomes) for the distinction. If rollback times out while an application exception is already active,
snekql preserves the application exception, logs the cleanup failure, and still
discards the connection.

## Close lifecycle and retry semantics

`Database.close()` moves a runtime through three states: accepting work,
closing, and closed. While closing, new transactions are rejected with
`DatabaseClosingError`; after a successful close they are rejected with
`DatabaseClosedError`. A successful `close()` is idempotent — calling it again
returns immediately.

Both backends share one owned shutdown operation across close callers. Native
`asyncio.Task.cancel()` cancels a caller's wait, not that shutdown operation.
The database continues rejecting work while shutdown runs; another `close()`
call joins the same operation instead of failing merely because it is closing.
Concurrent callers share its outcome, and joining does not restart its wait
budget. If all callers cancel, shutdown still finishes or times out, and an
otherwise unobserved failure is logged. A later call can retry after a timed-out
operation as described below. Cancelling a waiter does not forcibly stop a
SQLite worker thread that is still performing physical close.

When closing idle SQLite connections, a driver close failure does not skip the
remaining connections. The first failure is reported, failed handles remain
owned by the Database, and new work stays rejected. Call `close()` again to retry
those handles. Shutdown is not reported as successful until their cleanup
succeeds. This differs from a timeout waiting for checked-out work below.

Connections returned during SQLite shutdown use owned background cleanup too.
Shutdown waits for that cleanup instead of treating the returned lease as already
closed. A cancelled shutdown waiter does not abandon it. If physical discard or
returned-connection cleanup fails, the Database retains the failed handle and
rejects new work until `close()` can finish cleanup. A timeout waiting for other
Transactions does not clear this failed-cleanup state.

A close waits up to `acquire_timeout` for checked-out work to return. If that
wait elapses, `close()` raises `DatabaseCloseTimeoutError`. Behavior after a
timeout differs by backend, because the underlying drivers differ:

- **SQLite**: a timed-out close leaves the database **retryable**, provided no
  failed physical cleanup remains. The runtime returns to accepting work once
  checked-out connections come back, so callers
  can resume work or call `close()` again. (See
  `timed_out_close_keeps_database_retryable` in `tests/sqlite/test_runtime.py`.)
- **MariaDB**: a timed-out close is **terminal**. aiomysql's `pool.close()` is
  irreversible, so the runtime stays in the closing state and keeps rejecting
  work with `DatabaseClosingError`; it cannot be re-admitted. A later `close()`
  can still finish resource cleanup. (See
  `mariadb_close_timeout_keeps_pool_rejecting_new_work` in
  `tests/runtime/test_async_lifecycle.py`.)

Async services that catch `DatabaseCloseTimeoutError` must account for this:
on SQLite the runtime may still be usable, while on MariaDB it should be
treated as permanently unavailable.

See [connection lifecycle](connection-lifecycle.md) for the driver audit,
replacement policy, credential rotation, and application shutdown ordering.

## Execution context and parameter redaction

`ExecutionError` preserves parameterized SQL and raw values as explicit
attributes, but its string form and snekql's logs redact values by default:

```python
try:
    await tx.execute(statement)
except ExecutionError as error:
    logger.warning("snekql execution failed: %s", error)  # params=<redacted:N>
    inspect_locally(error.sql, error.params)  # explicit access
```

Use a Backend Config's `parameter_visibility="values"` only in a controlled
local diagnostic environment when raw values are required. That opt-in affects
query logs and `ExecutionError.__str__`; `.params` remains available for explicit
inspection under either policy. By default a chained driver error contributes
only its exception type, not its potentially value-bearing message. SQL stays
visible because Query Compilation binds values—including MariaDB JSON paths—
rather than interpolating them.

## JSON annotation enforcement

`pydantic.Json[T]` selects the JSON wire codec. Other `Annotated` metadata,
including constraints, validators and serializers, still applies to `T` in its
original order. This holds for SQLite text and MariaDB JSON/text storage.

Versions affected by metadata stripping, including 0.7.0, could accept values
that violated these rules or ignore a custom serializer. Corrected validation
can reject existing invalid rows during normal reads. Audit and repair those
rows explicitly; the fix does not rewrite stored data. Restoring a serializer
can also change future wire output, so check that old rows remain readable and
plan any required data migration. `validate=False` remains an explicit read-side
escape hatch for controlled inspection, not a substitute for repairing data.

## Agent guidance

When adding intentional failures inside snekql:

1. Raise a `SnekqlError` subclass.
2. Wrap external exceptions with exception chaining:
   `raise SnekqlErrorSubclass(message) from error`.
3. Preserve query context in `ExecutionError` when SQLite execution fails.

## Decimal precision and existing data

`CanonicalDecimal` normalization and native MariaDB `Decimal(precision, scale)`
checks are independent of Python's active decimal context. Canonical text keeps
all significant digits, removes fractional trailing zeros and writes signed zero
as `0`. Native decimal columns reject values that need rounding or exceed their
integer capacity; they do not silently round values to fit.

Versions affected by context-sensitive normalization, including 0.7.0, could
round canonical text or accept native values MariaDB then rounded. The corrected
code does not rewrite existing rows. Lost digits cannot be recovered from the
stored value alone. Audit affected data against a trusted source and reconcile it
through explicit application migrations. Check equality queries and unique keys
when repairing previously rounded values. Normal in-range canonical wire forms
remain unchanged; no blanket data conversion is required.

[All guides](README.md)
