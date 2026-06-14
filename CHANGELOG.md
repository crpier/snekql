# Changelog

## [Unreleased]

### Breaking changes

- Removed the `foreign_key=` parameter from `Integer`, `Real`, `Text`, `Blob`, and `DateTime`, and the primary-key-default foreign-key resolver. Foreign keys are now declared with the `ForeignKey(target_column)` specifier, which names the target column explicitly (including primary-key targets).
- SQLite connections now enforce foreign keys (`PRAGMA foreign_keys = ON`), so previously inert `FOREIGN KEY` constraints are now enforced on every write. MariaDB tables are created with `ENGINE=InnoDB` and enforce foreign keys via `foreign_key_checks`. Databases with pre-existing referential-integrity violations may surface errors on writes that touch the dangling rows; see [docs/engine-settings.md](./docs/engine-settings.md).
- MariaDB text columns are now created as `VARCHAR(255) ... COLLATE utf8mb4_bin` (case-sensitive) to match SQLite's default `BINARY` collation. Existing tables using the default case-insensitive collation are reported as schema drift.
- MariaDB runtime now requires MariaDB **>= 12.2**; older or non-MariaDB servers are rejected at initialization.

### Added

- `ForeignKey` column specifier, exported from the package root and the `sqlite`/`mariadb` backend namespaces. It records the referenced column on the descriptor, derives the column's storage class from that target, and cross-checks the target against the column's `FKCol[Target, T]` annotation at declaration time.
- Foreign keys may reference any unique non-primary-key target column (for example `User.email`), not only the target's single primary key.
- Centralized engine-settings seam that applies and verifies the connection settings snekql depends on, failing fast when a setting cannot be confirmed. SQLite verifies `foreign_keys`, `busy_timeout`, and UTF-8 `encoding` on every pooled connection; MariaDB verifies a strict `sql_mode` (`STRICT_ALL_TABLES`, `NO_ENGINE_SUBSTITUTION`), UTC `time_zone`, and `foreign_key_checks` on every physical connection, plus a minimum-version guard. Documented in [docs/engine-settings.md](./docs/engine-settings.md).

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
