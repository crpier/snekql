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

Model errors:

- `ModelDeclarationError`: invalid table model class or column declaration.
- `ModelValidationError`: invalid pending or fetched model value.
- `FrozenModelError`: attempt to mutate an immutable model instance.

Query errors:

- `QueryConstructionError`: invalid builder method call, such as
  `where()` with no predicates, passing a single-value select to
  `fetch_one_or_none` (whose `None` would be ambiguous), or calling
  `fetch_chunks(..., size=N)` with a non-positive `size`.
- `QueryCompilationError`: a built query cannot compile to valid v1 SQLite SQL,
  such as executing a select without `.where(...)` or `.all()`.

Runtime errors:

- `DatabaseClosedError`: work was requested after a successful close.
- `DatabaseClosingError`: new work was requested while close is in progress.
- `DatabaseCloseTimeoutError`: close timed out waiting for checked-out work.
- `PoolTimeoutError`: no connection became available before acquisition timeout.
- `TransactionClosedError`: a transaction was used after it closed.
- `NoResultError`: `fetch_one` found no row for its exactly-one contract.
- `MultipleResultsError`: `fetch_one`/`fetch_one_or_none` matched more than one
  row.
- `ExecutionError`: SQLite execution failed and query context is available.

Schema errors:

- `SchemaVerificationError`: an existing table does not match generated DDL.

Migration errors:

- `MigrationError`: a hand-authored migration body failed to apply. The message
  names the failing migration; previously-applied migrations stay recorded so a
  fixed retry resumes from the failure point (see [migrations.md](migrations.md)).
- `MigrationLockTimeoutError`: the migration advisory lock could not be acquired
  before the timeout because another instance was migrating. The losing instance
  applied nothing; a retry after the holder finishes applies only what is still
  pending.

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

## Execution context

`ExecutionError` preserves SQL text and raw parameter values:

```python
try:
    await tx.execute(statement)
except ExecutionError as error:
    logger.warning(
        "snekql execution failed: %s params=%r", error.sql, error.params
    )
```

`str(error)` includes SQL and parameter reprs for debugging. snekql's own
runtime logs may also include SQL and params exactly as supplied to the driver.
snekql does not redact secrets; applications should encrypt or safely represent
private values before they reach the Query Runtime.

## Agent guidance

When adding intentional failures inside snekql:

1. Raise a `SnekqlError` subclass.
2. Wrap external exceptions with exception chaining:
   `raise SnekqlErrorSubclass(message) from error`.
3. Preserve query context in `ExecutionError` when SQLite execution fails.
