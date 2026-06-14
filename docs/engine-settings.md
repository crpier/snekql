# Engine settings snekql applies and verifies

snekql's correctness guarantees depend on a small set of database engine
settings being in effect. Rather than assuming a well-configured server, snekql
**applies** each required setting and then **reads it back** to confirm it took
effect. A setting that cannot be applied or verified raises
`DatabaseRuntimeError` at initialization instead of degrading silently.

Per-connection settings are applied to *every* connection the pool opens, not
just the first, because the engines apply them per connection.

## SQLite (per connection)

Applied and verified in `open_sqlite_connection`:

| Setting | Value | Why |
| --- | --- | --- |
| `PRAGMA foreign_keys` | `ON` | SQLite does not enforce `FOREIGN KEY` constraints unless this is on. Without it the emitted constraints are inert. |
| `PRAGMA busy_timeout` | `5000` ms | The pool opens several connections to one database file; a busy timeout lets writers serialize instead of failing immediately with "database is locked". |
| `PRAGMA encoding` | `UTF-8` | Verified (not set): snekql stores and compares text as UTF-8. |

`STRICT` tables are enforced at DDL-compile time and checked during schema drift
verification; see [schema-drift.md](./schema-drift.md).

`journal_mode` (WAL) and `synchronous` are **not** managed by snekql. They are
performance/durability trade-offs left to the application to tune.

## MariaDB

### Minimum version

snekql verifies the server is MariaDB and at least **12.2**. Older MariaDB
builds and non-MariaDB servers (such as MySQL) are rejected at initialization.
The minimum may be lowered as more versions are validated.

### Session settings (per connection)

| Setting | Value | Why |
| --- | --- | --- |
| `sql_mode` | includes `STRICT_ALL_TABLES`, `NO_ENGINE_SUBSTITUTION` | `STRICT_ALL_TABLES` is the runtime analogue of SQLite `STRICT` tables: invalid or out-of-range values are rejected, not silently coerced. `NO_ENGINE_SUBSTITUTION` turns a missing storage engine into an error instead of a silent swap. |
| `time_zone` | `+00:00` | Server-side `CURRENT_TIMESTAMP` defaults are generated in UTC to match snekql's UTC datetime codec. |
| `foreign_key_checks` | `1` | Keeps the emitted `FOREIGN KEY` constraints enforced. |

### Table DDL

`CREATE TABLE` is emitted with `ENGINE=InnoDB`. InnoDB is the MariaDB analogue
of the SQLite `foreign_keys` pragma: non-transactional engines such as MyISAM
parse `FOREIGN KEY` clauses but silently ignore them. An existing table on a
different engine is reported as schema drift.

Text columns are emitted as `VARCHAR(255) CHARACTER SET utf8mb4 COLLATE
utf8mb4_bin`. The `utf8mb4_bin` collation makes string equality and `UNIQUE`
constraints **case-sensitive**, matching SQLite's default `BINARY` collation, so
the two backends agree on uniqueness and comparisons. The default utf8mb4
collation is case-insensitive and would diverge.

## Migration note: enabling foreign keys

Turning on foreign-key enforcement (SQLite `PRAGMA foreign_keys = ON`, MariaDB
`foreign_key_checks = 1` with InnoDB) affects **new** writes immediately. Rows
that already violate referential integrity from before enforcement was enabled
are not retroactively rejected at connection time, but a later write that
touches them can fail. Audit and clean up dangling references before adopting a
snekql version that enforces foreign keys.
