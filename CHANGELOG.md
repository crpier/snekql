# Changelog

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
