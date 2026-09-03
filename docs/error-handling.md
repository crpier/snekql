# Error handling guide

Every intentional package-originated exception is a `SnekqlError` subclass.
Application boundaries can catch `SnekqlError` for all expected snekql failures
and let unrelated programming errors continue to surface normally.

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
- **Entering twice** → `TransactionReuseError`, whether the transaction is still
  open (`already in progress`) or already used and closed. A transaction cannot
  be restarted.
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

## Transaction operation deadlines

Both Backend Configs default `operation_timeout` to 30 seconds. With no override,
connection acquisition uses `acquire_timeout`, while transaction begin, each
query operation, stream open/fetch/close, commit, and rollback each receive a
fresh `operation_timeout` budget. The timer does not include application code
between database calls and is not one deadline for the transaction's total
lifetime.

`db.transaction(timeout=N)` overrides **both** budgets for that transaction:
connection acquisition and every driver operation use `N`. This makes one call
site sufficient for short jobs while keeping pool and operation defaults
independently configurable.

A timed-out query or transaction-control call leaves physical connection state
uncertain ([ADR 0017](adr/0017-per-operation-deadlines-fail-closed.md)). The
Transaction becomes unusable and discards that connection instead
of returning it to the pool. A commit timeout raises
`DatabaseOperationTimeoutError`; whether the server committed is necessarily
ambiguous and must be resolved with an idempotency key or application-level
read. If rollback times out while an application exception is already active,
snekql preserves the application exception, logs the cleanup failure, and still
discards the connection.

## Close lifecycle and retry semantics

`Database.close()` moves a runtime through three states: accepting work,
closing, and closed. While closing, new transactions are rejected with
`DatabaseClosingError`; after a successful close they are rejected with
`DatabaseClosedError`. A successful `close()` is idempotent — calling it again
returns immediately.

A close waits up to `acquire_timeout` for checked-out work to return. If that
wait elapses, `close()` raises `DatabaseCloseTimeoutError`. Behavior after a
timeout differs by backend, because the underlying drivers differ:

- **SQLite**: a timed-out close leaves the database **retryable**. The runtime
  returns to accepting work once checked-out connections come back, so callers
  can resume work or call `close()` again. (See
  `timed_out_close_keeps_database_retryable` in `tests/sqlite/test_runtime.py`.)
- **MariaDB**: a timed-out close is **terminal**. aiomysql's `pool.close()` is
  irreversible, so the runtime stays in the closing state and keeps rejecting
  work with `DatabaseClosingError`; it cannot be re-admitted. (See
  `mariadb_close_timeout_keeps_pool_rejecting_new_work` in
  `tests/runtime/test_async_lifecycle.py`.)

Async services that catch `DatabaseCloseTimeoutError` must account for this:
on SQLite the runtime may still be usable, while on MariaDB it should be
treated as permanently unavailable.

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

## Agent guidance

When adding intentional failures inside snekql:

1. Raise a `SnekqlError` subclass.
2. Wrap external exceptions with exception chaining:
   `raise SnekqlErrorSubclass(message) from error`.
3. Preserve query context in `ExecutionError` when SQLite execution fails.
