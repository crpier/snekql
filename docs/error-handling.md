# Error handling guide

Every intentional package-originated exception is a `SnekqlError` subclass.
Application boundaries can catch `SnekqlError` for all expected snekql failures
and let unrelated programming errors continue to surface normally.

```python
from snekql import SnekqlError

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
  `where()` with no predicates.
- `QueryCompilationError`: a built query cannot compile to valid v1 SQLite SQL,
  such as executing a select without `.where(...)` or `.all()`.

Runtime errors:

- `DatabaseClosedError`: work was requested after a successful close.
- `DatabaseClosingError`: new work was requested while close is in progress.
- `DatabaseCloseTimeoutError`: close timed out waiting for checked-out work.
- `PoolTimeoutError`: no connection became available before acquisition timeout.
- `TransactionClosedError`: a transaction was used after it closed.
- `ExecutionError`: SQLite execution failed and query context is available.

Schema errors:

- `SchemaVerificationError`: an existing table does not match generated DDL.

## Execution context

`ExecutionError` preserves SQL text and raw parameter values:

```python
try:
    await tx.execute(statement)
except ExecutionError as error:
    logger.warning(
        "snekql execution failed",
        extra={"sql": error.sql, "params": error.params},
    )
```

`str(error)` includes SQL and parameter reprs for debugging. snekql does not
attempt secret redaction beyond using each value's normal `repr`.

## Agent guidance

When adding intentional failures inside snekql:

1. Raise a `SnekqlError` subclass.
2. Wrap external exceptions with exception chaining:
   `raise SnekqlErrorSubclass(message) from error`.
3. Preserve query context in `ExecutionError` when SQLite execution fails.
