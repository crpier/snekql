# Changelog

## 0.1.0 - 2026-05-31

Initial v1 release.

- Typed table model declarations with pending/fetched lifecycle states.
- SQLite-first storage declarations and logical codecs.
- Immutable query builders for single-table select/insert/update/delete.
- Async SQLite runtime with bounded connection pool and transactions.
- Deterministic SQLite `STRICT` table creation and schema verification.
- Public `SnekqlError` exception hierarchy.
- PEP 561 typing support with `py.typed` and a public facade stub.
