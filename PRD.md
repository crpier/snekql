# snekql v1 PRD

## Problem Statement

snekql should provide a Python-only, async-first typed query builder and query runtime for SQLite `STRICT` tables. It must give applications explicit SQL-shaped operations, strong type-checker ergonomics, runtime validation, schema startup support, and transaction-based execution without becoming an ORM.

The product should optimize for a small, clear v1 surface rather than broad database coverage. SQLite is the only v1 dialect. Future dialects may be considered later, but v1 APIs should not pretend to be cross-database abstractions where SQLite behavior is the real contract.

## Product Goals

- Provide a strongly typed table model declaration API.
- Provide typed single-table `select`, `insert`, `update`, and `delete` query builders.
- Provide an async SQLite runtime backed by a bounded connection pool.
- Keep Query Builder and Query Runtime separate.
- Keep all operations explicit and SQL-shaped.
- Avoid ORM behavior: no identity map, relationship loading, lazy loading, session/unit-of-work abstraction, or mutation persistence.
- Generate deterministic SQLite `STRICT` `CREATE TABLE` statements from models.
- Create missing tables and detect drift for existing tables at database initialization.
- Validate Python construction and fetched database values through Pydantic-backed validation.
- Ensure every intentional package-originated exception is a `SnekqlError` subclass.

## Non-Goals

- Full ORM behavior.
- Joins in v1.
- Raw SQL execution in v1.
- Sync database access.
- Multiple SQL dialects in v1.
- Migrations or altering existing tables.
- Public materialization helpers for constructing fetched models in tests.
- Text length enforcement or `Varchar` support.
- Streaming result APIs in v1.

## Canonical Public API

### Model Declaration

```python
from __future__ import annotations

from datetime import datetime

from snekql import (
    MISSING,
    CurrentTimestamp,
    DateTime,
    Fetched,
    Integer,
    Model,
    Pending,
    Text,
)

class User[S = Pending](Model[S, "User[Fetched]"]):
    id: User.GenCol[int] = Integer(
        primary_key=True,
        auto_increment=True,
        default=MISSING,
    )
    email: User.Col[str] = Text(nullable=False)
    status: User.Col[str] = Text(nullable=False, default="active")
    created_at: User.GenCol[datetime] = DateTime(
        server_default=CurrentTimestamp(),
        default=MISSING,
    )
```

Requirements:

- Model classes directly subclass `Model[S, "ModelName[Fetched]"]`.
- `Pending` is the default state for direct construction.
- `Fetched` is the state returned by database reads.
- `Col[T]` declares normal persisted columns.
- `GenCol[T]` declares generated/server-filled columns whose pending value is `T | Missing` and fetched value is `T`.
- No `Annotated[...]` declaration path in v1.
- No backing-field/public-field duplication.
- No `ClassVar[...]` descriptor duplication.
- No column aliasing in v1; Python field name is SQL column name.
- Direct model construction produces pending models:
  ```python
  user = User(email="alice@example.com")  # User[Pending]
  ```
- Fetched models are produced by database reads only.
- No public `materialize(...)` helper in v1.

### Table Names And Identifiers

- If `__tablename__` is omitted, table name is inferred from class name by converting to `snake_case` without pluralization:
  - `User` -> `user`
  - `AuditLog` -> `audit_log`
- Models may override the inferred name:
  ```python
  class User[S = Pending](Model[S, "User[Fetched]"]):
      __tablename__ = "users"
  ```
- Table names must match a simple SQL identifier rule such as `[A-Za-z_][A-Za-z0-9_]*`.
- Column names use Python field names and must pass the same identifier validation.
- Generated SQL always quotes identifiers with SQLite double quotes.
- Reserved keywords are allowed because identifiers are always quoted.
- Internal model schema metadata is frozen at class creation.
- Later Python class attribute mutation does not affect snekql schema/query behavior.

### Model Body Rules

- V1 table models must be direct `Model[...]` subclasses.
- Subclassing a concrete model raises `ModelDeclarationError`.
- Abstract model bases and column mixins are out of scope for v1.
- Model class bodies may contain:
  - snekql column declarations,
  - methods,
  - `ClassVar` constants,
  - optional `__tablename__`.
- Plain instance annotations that are not snekql columns are rejected.
- `@property` computed attributes are not supported in v1.
- Methods are allowed unless they conflict with column names or reserved snekql internals.

### Model Value Semantics

- Model instances are immutable after construction/materialization.
- Post-init assignment to a column raises `FrozenModelError`.
- Model `repr` includes model state and omits `MISSING` fields:
  ```python
  User[Pending](email='alice@example.com')
  User[Fetched](id=1, email='alice@example.com')
  ```
- Equality uses normal Python value equality, including `MISSING` values.
- Models are not hashable.
- JSON/list/dict fields use normal Python equality; no JSON normalization is applied for equality.

## SQLite Storage Types

V1 storage classes:

- `Integer`
- `Real`
- `Text`
- `Blob`
- `Json`
- `Boolean`
- `DateTime`

Requirements:

- No `Varchar` in v1.
- `Text` has no length option.
- Column type classes should expose SQLite-backed behavior only; app-level constraints like text length are out of scope unless SQLite itself enforces them natively.
- SQLite DDL always generates `STRICT` tables.
- Existing non-`STRICT` tables are schema drift.

### Logical SQLite Encodings

- `Json` compiles to SQLite `TEXT`.
- `Json` values are serialized to JSON text before writes/query parameters and deserialized before fetched-row validation.
- `Boolean` compiles to SQLite `INTEGER`.
- `Boolean` encodes `False` as `0` and `True` as `1`.
- `DateTime` compiles to SQLite `TEXT`.
- `DateTime` accepts only timezone-aware `datetime` values.
- `DateTime` values are normalized to UTC, truncated to milliseconds, and encoded as:
  ```text
  YYYY-MM-DDTHH:MM:SS.SSSZ
  ```
- Fetched `DateTime` values are parsed into timezone-aware UTC `datetime` objects.
- `CurrentTimestamp()` is the only v1 server default.
- `CurrentTimestamp()` is valid only on `DateTime` fields.
- `DateTime(server_default=CurrentTimestamp())` compiles for SQLite as a deterministic current-time default compatible with the chosen storage format, e.g. `strftime('%Y-%m-%dT%H:%M:%fZ', 'now')`.
- V1 does not generate extra CHECK constraints for `Json`, `Boolean`, or `DateTime` logical validity.

### Generated Columns And Primary Keys

- Every `GenCol` in v1 must declare `default=MISSING`.
- Any field with `server_default` must be a `GenCol`.
- `auto_increment=True` requires:
  - `Integer`,
  - `GenCol[int]`,
  - `primary_key=True`,
  - `default=MISSING`.
- Primary keys are not required in v1.
- Primary key fields are selectable, orderable, and predicate-capable.
- Primary key fields are not update-assignable.
- `GenCol` fields are selectable, orderable, and predicate-capable.
- `GenCol` fields are not update-assignable; `GenCol.to(...)` should be absent statically if feasible and always rejected at runtime.

## Query Builder

### General Query Rules

- Query builders are immutable; chain methods return new query objects.
- Query builder misuse fails before SQL execution with a `QueryError` subclass.
- Compiled SQL is parameterized.
- Identifiers are always double-quoted.
- Query builder and runtime are separate; queries can be built before a database runtime exists.

### Predicates

- Predicate construction uses explicit methods only; Python comparison operators are not part of the v1 API.
- Supported predicate methods include:
  - `.eq(value)`,
  - `.ne(value)`,
  - `.is_null()`,
  - `.is_not_null()`,
  - `.in_(...)`,
  - `.not_in(...)`,
  - `.like(...)`,
  - `.not_like(...)`.
- Boolean composition uses `&`, `|`, and `~`.
- Predicate objects must not be truthy/falsy in Python boolean contexts.
- `.is_null()` and `.is_not_null()` are available on all columns, not only nullable ones.
- `eq(None)` and `ne(None)` are invalid; callers must use `.is_null()` and `.is_not_null()`.
- `in_()` and `not_in()` require at least one value and do not accept `None` in v1.
- `like()` and `not_like()` are valid only for text/string fields, statically if feasible and always at runtime.
- Boolean fields have no special v1 helpers; callers use `.eq(True)` / `.eq(False)`.

### Select

Supported forms:

```python
select(User)
select(User.email)
select(User.email, User.status)
```

Requirements:

- `select(User)` returns `SelectModelQuery[User, User[Fetched]]` and runtime rows of `User[Fetched]`.
- `select(User.email)` returns a single-value query and runtime values of `str` for this example.
- `select(User.email, User.status)` returns tuple rows in selection order.
- Mixed model+field selection is forbidden in v1.
- Joins are not supported in v1.
- A select query must explicitly choose either filtered or unfiltered operation before compile/execute:
  ```python
  select(User).where(User.email.eq("x"))
  select(User).all()
  ```
- `.where(...)` and `.all()` are mutually exclusive.
- `.where(...)` accepts one or more predicates, may be called multiple times, and all predicates are ANDed.
- `.where()` with zero predicates is rejected statically if feasible and at runtime.
- Repeated `.all()` is a no-op and returns `self`.
- `.order_by(...)` requires at least one ordering and repeated calls append.
- `.limit(...)` and `.offset(...)` accept non-negative integers only.
- Repeated `.limit(...)` replaces the previous limit.
- Repeated `.offset(...)` replaces the previous offset.
- `.offset(...)` without `.limit(...)` is allowed for SQLite and compiles using SQLite's `LIMIT -1 OFFSET ?` pattern.
- Public `.limit(-1)` is invalid.
- `.limit(0)` is valid.

### Insert

```python
stmt = insert(User(email="alice@example.com"))
```

Requirements:

- Insert accepts a pending model instance.
- Insert omits fields whose value is `MISSING`.
- Insert includes Python default/default-factory values because they are real model values.
- If all insertable fields are `MISSING`, compile `INSERT INTO "table" DEFAULT VALUES`.
- Insert SQL is parameterized.

### Update

```python
stmt = (
    update(User)
    .set(User.status.to("disabled"), User.email.to("new@example.com"))
    .where(User.email.eq("old@example.com"))
)
```

Requirements:

- `.set(...)` requires at least one assignment, statically if feasible and at runtime.
- `.set(...)` accepts multiple assignments.
- Update assignments must belong to the target model.
- Generated columns and primary key columns are not update-assignable.
- Update must choose exactly one of `.where(...)` or `.all()` before compile/execute.
- `.where(...)` and `.all()` are mutually exclusive.
- `.where(...)` follows the same accumulation rules as select.
- `update(User).set(...).all()` is the explicit full-table update form.

### Delete

```python
stmt = delete(User).where(User.email.eq("retired@example.com"))
stmt = delete(User).all()
```

Requirements:

- Delete targets exactly one model.
- Delete must choose exactly one of `.where(...)` or `.all()` before compile/execute.
- `.where(...)` and `.all()` are mutually exclusive.
- `delete(User).all()` is the explicit full-table delete form.

## Query Runtime

### Database Initialization

```python
from pathlib import Path

db = await Database.initialize(
    database=Path("app.db"),
    models=[User, AuditLog],
    schema_policy="strict",
    pool_size=5,
    acquire_timeout=30.0,
)

memory_db = await Database.initialize(database=":memory:")
```

Requirements:

- `Database.initialize(...)` is the only public construction path for `Database`.
- There is no public half-initialized `Database(...)` object.
- SQLite v1 uses a required keyword-only `database` parameter instead of a DSN.
- `database` accepts `pathlib.Path` for file-backed SQLite databases.
- `database` also accepts the exact string `":memory:"` for an in-memory SQLite database.
- Plain string file paths such as `"app.db"` are rejected in v1.
- URL-style DSNs such as `"sqlite:///app.db"` and `"sqlite:///:memory:"` are rejected in v1.
- Other `os.PathLike`, bytes paths, and driver-specific connection strings are rejected in v1.
- Future dialects may add their own dedicated keyword-only connection parameters rather than overloading a cross-dialect DSN string.
- `models` is optional; omitting models initializes connectivity only.
- `schema_policy` supports `"strict"` and `"warn"`; default is `"strict"`.
- `pool_size` is a fixed maximum connection count; default is `5` and it must be at least `1`.
- `acquire_timeout` is seconds as `float`; default is `30.0`; it must be non-negative.
- `acquire_timeout=0.0` means fail immediately if no connection is available.
- Initialization proves connectivity with at least one connection.
- Additional connections are created lazily up to `pool_size`.

### Transactions

```python
async with db.transaction(timeout=5.0) as tx:
    ...
```

Requirements:

- `db.transaction(...)` is the only public transaction-starting API.
- `Database` itself is not an async transaction context manager.
- `transaction(timeout=...)` overrides the database default acquisition timeout for that transaction.
- If timeout is omitted, the database `acquire_timeout` is used.
- Entering a transaction acquires a connection and issues `BEGIN`.
- Successful exit issues `COMMIT`.
- Exceptional exit issues `ROLLBACK` and re-raises.
- All work inside a transaction uses the same connection.
- Nested/concurrent transactions are not blocked by snekql; they are independent pool checkouts and driver/database behavior applies.
- Pool exhaustion waits up to the relevant acquisition timeout, then raises `PoolTimeoutError`.

### Runtime Methods

```python
await tx.fetch_all(select(User).all())
await tx.fetch_one(select(User).where(User.email.eq("x")))
await tx.execute(insert(User(email="x")))
```

Requirements:

- `fetch_all(select(User))` returns `list[User[Fetched]]` after query completeness validation.
- `fetch_all(select(User.email))` returns `list[str]` for this example.
- `fetch_all(select(User.email, User.status))` returns `list[tuple[str, str]]`.
- `fetch_one(...)` returns the first row or `None`.
- `fetch_one(...)` does not validate cardinality, does not inject `LIMIT`, and does not warn if the query has no limit.
- `fetch_one(...)` closes/discards cursor resources promptly after reading the first row.
- `fetch_one(...limit(0))` returns `None`.
- `execute(...)` accepts only insert/update/delete statements.
- `execute(...)` does not accept selects.
- `execute(...)` returns `None` in v1.
- No streaming/iteration API in v1.
- No raw SQL execution API in v1.

### Database Close

Requirements:

- `await db.close()` closes the database runtime.
- Successful `close()` is idempotent; repeated calls after success are no-ops.
- Closing stops accepting new transactions while close is in progress.
- Idle connections close immediately.
- Checked-out transactions are allowed to finish until `acquire_timeout` elapses.
- If close times out, raise `DatabaseCloseTimeoutError`, keep the database open, and allow close to be retried.
- After a failed close attempt, new transactions are accepted again.
- Using a successfully closed database raises `DatabaseClosedError`.

## Schema Management

### Initialization Behavior

When `Database.initialize(..., models=[...])` is called:

- Preserve the order of the `models` sequence.
- Reject duplicate resolved table names, even if they come from different model classes.
- Create missing tables.
- Verify existing tables.
- Skip verification for tables created during the same initialization pass.
- Run schema setup in a transaction where SQLite supports it.
- Under `strict`, schema drift raises `SchemaVerificationError` and rolls back schema setup.
- Under `warn`, schema drift is logged, startup continues, and schema setup commits.

### V1 Verification Strategy

Keep verification deliberately simple:

1. Generate expected deterministic SQLite `CREATE TABLE` SQL for each model.
2. Read existing table SQL from SQLite metadata.
3. Normalize only formatting that snekql itself controls.
4. Compare generated SQL and existing SQL.
5. Treat mismatch as schema drift.

The generated SQL must include `STRICT`; therefore non-`STRICT` tables drift.

## Validation And Pydantic Integration

Requirements:

- Model construction validates and coerces pending values through Pydantic-backed validation.
- Fetched row materialization validates and coerces database values through Pydantic-backed validation.
- Assignment during construction/materialization uses descriptor `__set__` mechanics, but post-init assignment raises `FrozenModelError`.
- JSON text is decoded before final model validation.
- DateTime text is parsed before final model validation.
- External validation errors, including Pydantic errors, are caught and wrapped in `SnekqlError` subclasses.
- Runtime validation is authoritative even when static type checking cannot express a rule.

## Error Model

All intentional `raise` statements from snekql must raise `SnekqlError` subclasses. External exceptions must be wrapped with exception chaining via `raise ... from exc`.

Recommended hierarchy:

```python
class SnekqlError(Exception): ...

class ModelError(SnekqlError): ...
class ModelDeclarationError(ModelError): ...
class ModelValidationError(ModelError): ...
class FrozenModelError(ModelError): ...

class QueryError(SnekqlError): ...
class QueryConstructionError(QueryError): ...
class QueryCompilationError(QueryError): ...

class DatabaseRuntimeError(SnekqlError): ...
class DatabaseClosedError(DatabaseRuntimeError): ...
class DatabaseClosingError(DatabaseRuntimeError): ...
class DatabaseCloseTimeoutError(DatabaseRuntimeError): ...
class PoolTimeoutError(DatabaseRuntimeError): ...
class TransactionClosedError(DatabaseRuntimeError): ...
class ExecutionError(DatabaseRuntimeError): ...

class SchemaError(SnekqlError): ...
class SchemaVerificationError(SchemaError): ...
```

Execution failures must preserve query context:

- `ExecutionError.sql` contains the SQL text.
- `ExecutionError.params` contains the raw parameter tuple.
- `str(error)` includes SQL and parameter reprs with truncation for huge output.
- snekql does not attempt secret redaction beyond respecting safe `repr` implementations of user values.

## Testing Requirements

- Static typing prototypes must remain pyright-clean.
- Model tests must cover declaration rules, table-name inference, invalid annotations, defaults, `Missing`, immutability, equality, and `repr`.
- Storage type tests must cover SQLite type generation, DateTime encoding/decoding, Boolean encoding/decoding, JSON encoding/decoding, and invalid generated/server-default combinations.
- Query builder tests must cover generated SQL, parameter order, `.all()`/`.where()` completeness, update/delete full-table opt-in, predicate composition, invalid predicate usage, and immutable builder behavior.
- Runtime tests must cover `Database.initialize`, pool acquisition timeout, transaction begin/commit/rollback, fetch result conversion, `fetch_one` first-row behavior, `execute` returning `None`, close semantics, and wrapped execution errors.
- Schema tests must cover create missing tables, verify existing tables, strict/warn drift policy, duplicate table names, non-`STRICT` drift, and generated SQL comparison.
- Integration tests should run against a real SQLite `Path` database and `database=":memory:"`.
