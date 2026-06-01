# Changelog

## 0.2.0 - 2026-06-01

### Breaking changes

- `Database.initialize(...)` now requires a structured logger as the first argument.
- Backend drivers are optional extras; install `snekql[aiosqlite]` for SQLite runtime support and `snekql[aiomysql]` for MariaDB runtime support.
- Table models carry backend identity, and runtime initialization/execution rejects mixed-backend models and queries.

### Added

- MariaDB backend namespace, runtime configuration, schema startup, query execution, value codecs, indexes, and schema drift verification.
- Structured Query Runtime logging for database initialization, schema startup, transactions, query execution, pool lifecycle, shutdown, and failures.
- Public `StructuredLogger` protocol for structlog-style application loggers.
- Schema index support for column-level unique indexes and table-level indexes.
- Adoption and MariaDB documentation, including release confidence guidance and runnable examples.

### Changed

- Refactored SQLite runtime behind backend-neutral runtime adapter seams.
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
