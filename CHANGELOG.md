# Changelog

## [Unreleased]

### Breaking changes

- Table Model field values are now validated against their declared logical type with a strict per-column pydantic `TypeAdapter`, both when constructing a Pending Model and when materializing a Fetched Model. Values that previously slipped through column coercion (for example a `bool` or `float` for an `Integer` column, or a JSON payload that does not match its annotated container shape) now raise `ModelValidationError`. The logical type comes from the column's `Col[T]` / `GenCol[T]` / `FKCol[Target, T]` annotation.
- `DateTime` columns now require timezone-aware `datetime` values and reject naive ones (validated via pydantic `AwareDatetime`). UTC and millisecond canonicalization happen only when the value crosses the database boundary, so a Pending Model now holds the raw aware `datetime` you constructed it with rather than a pre-normalized UTC value.
- `Json` columns validate the annotated container shape at construction; JSON serializability is now a wire-codec concern checked only when the value is encoded for storage. A value matching the annotated shape but not serializable is accepted at construction and rejected at encode time.
- Removed the `foreign_key=` parameter from `Integer`, `Real`, `Text`, `Blob`, and `DateTime`, and the primary-key-default foreign-key resolver. Foreign keys are now declared with the `ForeignKey(target_column)` specifier, which names the target column explicitly (including primary-key targets).
- SQLite connections now enforce foreign keys (`PRAGMA foreign_keys = ON`), so previously inert `FOREIGN KEY` constraints are now enforced on every write. MariaDB tables are created with `ENGINE=InnoDB` and enforce foreign keys via `foreign_key_checks`. Databases with pre-existing referential-integrity violations may surface errors on writes that touch the dangling rows; see [docs/engine-settings.md](./docs/engine-settings.md).
- MariaDB text columns are now created as `VARCHAR(255) ... COLLATE utf8mb4_bin` (case-sensitive) to match SQLite's default `BINARY` collation. Existing tables using the default case-insensitive collation are reported as schema drift.
- MariaDB runtime now requires MariaDB **>= 12.2**; older or non-MariaDB servers are rejected at initialization.

### Added

- Versioned migrations: `Database.initialize(..., migrations={...})` accepts an ordered `dict[str, str]` of migration name to raw SQL body. snekql ensures a snekql-owned `snekql_migrations` history table, runs each pending migration (mapping keys not yet recorded) once in insertion order, and records each success. Migrations are hand-authored and never generated. When `migrations` is provided they are the sole schema-creation authority (models are verified, not auto-created), so a model with no matching migration is reported as drift under `strict`. snekql does not wrap a migration body and its history row in one transaction (bodies are applied as-is and must be idempotent); a failing body halts startup with the new `MigrationError`, naming the migration, while already-applied migrations stay recorded. v1 does not coordinate concurrent runs. See [docs/migrations.md](./docs/migrations.md) and [docs/adr/0001-hand-authored-raw-sql-migrations.md](./docs/adr/0001-hand-authored-raw-sql-migrations.md).
- `Database.migrate(...)` classmethod: a standalone surface that applies pending migrations from a dedicated deploy step without a full `initialize()`. It accepts the same backend selection as `initialize` (a `database=` path or a backend `Config`) plus a required `migrations` mapping, shares the exact apply runner and idempotency semantics (each migration runs once and is recorded in the Migration History), but takes no `models`, runs no schema startup or drift verification, opens no connection pool, and returns nothing. This is the recommended single place to run migrations under v1's no-coordination concurrency model. See [docs/migrations.md](./docs/migrations.md).
- `MigrationError` exception (a `SnekqlError`), exported from the package root, raised when a migration body fails to apply.
- Ordered-comparison and range column predicates: `.gt(...)`, `.gte(...)`, `.lt(...)`, `.lte(...)`, and `.between(low, high)`. They compile to `> >= < <=` and `BETWEEN ? AND ?`, are scope-checked and composable with `&`/`|`/`~` like the existing predicates, and reject `None` arguments (steering callers at `is_null()`/`is_not_null()`).
- `ForeignKey` column specifier, exported from the package root and the `sqlite`/`mariadb` backend namespaces. It records the referenced column on the descriptor, derives the column's storage class from that target, and cross-checks the target against the column's `FKCol[Target, T]` annotation at declaration time.
- Foreign keys may reference any unique non-primary-key target column (for example `User.email`), not only the target's single primary key.
- Centralized engine-settings seam that applies and verifies the connection settings snekql depends on, failing fast when a setting cannot be confirmed. SQLite verifies `foreign_keys`, `busy_timeout`, and UTF-8 `encoding` on every pooled connection; MariaDB verifies a strict `sql_mode` (`STRICT_ALL_TABLES`, `NO_ENGINE_SUBSTITUTION`), UTC `time_zone`, and `foreign_key_checks` on every physical connection, plus a minimum-version guard. Documented in [docs/engine-settings.md](./docs/engine-settings.md).
- `Model.construct(**values)` classmethod that builds a Pending Model while skipping per-column logical validation, for values already known to satisfy their declared types. Defaults, missing/unknown-field structural checks, and freezing still apply.
- `validate: bool = True` keyword on `Transaction.fetch_one` and `Transaction.fetch_all` (threaded through row materialization) to skip read-side logical validation for trusted result sets while keeping wire decoding.
- `Json` columns now serialize and decode through the same per-column pydantic `TypeAdapter` that drives validation (`dump_json` / `validate_json`), making the codec symmetric. Any type the `Col[T]` annotation can validate -- `datetime`, pydantic models, `list[Model]`, and so on -- now round-trips, rather than only `dict`/`list`/primitives. Native payloads keep the same compact, byte-stable text as before. A `validate=False` decode still returns the raw `json.loads` value with no type coercion.

### Notes

- Following pydantic's documented behavior, `Real` columns accept an `int` and widen it to `float` even under strict validation.

## 0.3.0 - 2026-06-07

### Breaking changes

- `Database.initialize(...)` now requires an explicit structured logger keyword argument.
- Backend drivers are optional extras; install `snekql[aiosqlite]` for SQLite runtime support and `snekql[aiomysql]` for MariaDB runtime support.
- Table models carry backend identity, and runtime initialization/execution rejects mixed-backend models and queries.

### Added

- MariaDB backend namespace, runtime configuration, schema startup, query execution, value codecs, indexes, and schema drift verification.
- Temporary MariaDB test-server support for local integration tests, including reset helpers and a CLI entry point.
- Structured Query Runtime logging for database initialization, schema startup, transactions, query execution, pool lifecycle, shutdown, and failures.
- Public `StructuredLogger` protocol for structlog-style application loggers.
- Schema index support for column-level unique indexes and table-level indexes.
- Adoption, schema drift, error-handling, typing, and MariaDB testing documentation with runnable examples.

### Changed

- Refactored SQLite runtime behind backend-neutral runtime adapter seams.
- Deepened query compilation through Dialect-owned SQL rendering instead of MariaDB translating SQLite-shaped SQL.
- Deepened schema startup through a shared schema plan while preserving backend-specific DDL and drift checks.
- Deepened Table Model materialization through shared Pending Model encoding, Fetched Model decoding, and backend column codecs.
- Deepened Backend Runtime Adapter selection so `Database` remains focused on lifecycle and transactions.
- Reorganized tests into backend-specific packages and removed redundant MariaDB test-server coverage.
- Updated package metadata to describe both SQLite and MariaDB support.

## 0.1.0 - 2026-05-31

Initial v1 release.

- Typed table model declarations with pending/fetched lifecycle states.
- SQLite-first storage declarations and logical codecs.
- Immutable query builders for single-table select/insert/update/delete.
- Async SQLite runtime with bounded connection pool and transactions.
- Deterministic SQLite `STRICT` table creation and schema verification.
- Public `SnekqlError` exception hierarchy.
- PEP 561 typing support with `py.typed` and a public facade stub.
