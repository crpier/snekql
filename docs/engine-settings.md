# Engine settings snekql applies and verifies

snekql's correctness guarantees depend on a small set of database engine
settings being in effect. Rather than assuming a well-configured server, snekql
**applies** each required setting and then **reads it back** to confirm it took
effect. A setting that cannot be applied or verified raises
`DatabaseRuntimeError` at initialization or later connection acquisition instead
of degrading silently.

Per-connection settings are applied to *every* connection the pool opens, not
just the first, because the engines apply them per connection.

## SQLite (per connection)

Applied and verified in `open_sqlite_connection`:

| Setting | Value | Why |
| --- | --- | --- |
| `PRAGMA journal_mode` | `WAL` (file-backed databases) | Gives pooled readers and the single writer predictable concurrency. This setting persists on the database file. |
| `PRAGMA synchronous` | `NORMAL` by default; `FULL` with `Config(durability="full")` | NORMAL can lose recent commits on OS crash or power loss. FULL adds a WAL sync at each commit. |
| `PRAGMA foreign_keys` | `ON` | SQLite does not enforce `FOREIGN KEY` constraints unless this is on. Without it the emitted constraints are inert. |
| `PRAGMA busy_timeout` | `5000` ms | The pool opens several connections to one database file; a busy timeout lets writers serialize instead of failing immediately with "database is locked". |
| `PRAGMA encoding` | `UTF-8` | Verified (not set): snekql stores and compares text as UTF-8. |

### Write contention and `mode="immediate"`

SQLite has one global, exclusive writer lock, regardless of `pool_size`: a
bigger pool buys more *open* transactions, not more concurrent writers. A plain
(deferred) transaction acquires no lock until its first write, so a transaction
that reads before it writes only discovers it cannot get the writer lock after
that read work is done — and under WAL a concurrent commit in that window turns
the write into an unrecoverable `SQLITE_BUSY_SNAPSHOT`.

For transactions known to write, declare it:

```python
async with db.transaction(mode="immediate") as tx:
    await tx.execute(insert(row))
```

`mode="immediate"` issues `BEGIN IMMEDIATE`, taking the writer lock up front so
contention is resolved fairly at acquisition rather than mid-transaction. The
`busy_timeout` PRAGMA makes a losing writer wait for the lock; on top of that,
snekql retries the acquisition with bounded exponential backoff and jitter
(`Config.busy_max_retries`, default 5; backoff bounded by `Config.busy_base_backoff`
and `Config.busy_max_backoff`) so a collision that outlasts the PRAGMA
wait is absorbed instead of surfacing. A genuinely stuck lock (for example an
external process holding the database) still surfaces as an error once the retry
budget is spent. Migration acquisition reports that exhaustion as
`MigrationLockTimeoutError`. Retry is applied only to writer-lock acquisition, never to a
statement inside an open transaction, because retrying a write after a
concurrent commit cannot clear `SQLITE_BUSY_SNAPSHOT`.

On MariaDB, `mode` is a no-op: InnoDB serializes writers with row-level locks,
so there is no single writer lock to acquire eagerly.

`STRICT` tables are enforced at DDL-compile time and checked during schema drift
verification; see [schema-drift.md](./schema-drift.md).

### SQLite durability policy

```python
from pathlib import Path
from snekql import sqlite

config = sqlite.Config(database=Path("app.db"), durability="full")
db = await sqlite.Database.initialize(config)
```

`durability` accepts exactly `"normal"` or `"full"`. The default `"normal"`
preserves existing behavior, including `Database.initialize(database=...)`.
The policy belongs to the Config for the pool's lifetime, not to a Transaction.

- Both file-backed policies apply and verify `journal_mode=WAL`.
- `"normal"` selects `synchronous=NORMAL`. Under SQLite's WAL guarantees,
  application crashes do not lose committed transactions, but OS crashes or
  power loss can lose recent commits. This can include more than one transaction.
- `"full"` selects `synchronous=FULL`. SQLite synchronizes the WAL after each
  transaction commit, requesting durability across OS crashes and power loss.
  Acknowledgement still depends on the filesystem, OS, device, and controller
  honoring synchronization requests. FULL does not repair unreliable storage,
  make volatile volumes persistent, or eliminate the need for tested backups.

Every physical connection applies and verifies the selected settings, including
initialization, lazy pool growth, and replacements after discarded connections.
Failure to read back the required settings rejects and closes that connection;
there is no fallback to a weaker policy. A new runtime reopening the file must
select its desired policy again because `synchronous` is connection-local.
Configure other processes opening the same database consistently too.

The exact `":memory:"` target stays volatile and single-connection. Its default
policy leaves SQLite's native journal and synchronization settings unchanged.
`durability="full"` rejects in-memory targets at Config construction, including
`Path(":memory:")`, which SQLite also interprets as its special memory target.
Other durability values, including OFF and EXTRA, are unsupported.

The policy covers the configured main database, not databases added through raw
`ATTACH`. Do not override managed PRAGMAs or transaction control through raw SQL.
WAL requires storage with the locking and shared-memory behavior SQLite expects;
network filesystems are not a substitute for a supported local storage setup.
Tests verify configuration and connection lifecycle behavior, not physical
power-loss survival. See SQLite's [synchronous documentation](https://www.sqlite.org/pragma.html#pragma_synchronous)
and [WAL documentation](https://www.sqlite.org/wal.html).

## MariaDB

### Verified TLS

MariaDB TCP connections can require certificate verification through the typed
`TLSConfig` path:

```python
from pathlib import Path
from snekql import mariadb

config = mariadb.Config(
    database="app",
    host="db.internal.example",
    user="snekql",
    password="from-secret-store",
    tls=mariadb.TLSConfig(ca_file=Path("/etc/app/database-ca.pem")),
)
```

`TLSConfig` always uses `CERT_REQUIRED`, hostname checking, and TLS 1.2 or newer.
Omit `ca_file` to use system trust roots. Mutual TLS is available by supplying
both `cert_file` and `key_file`; supplying only one is rejected.
TLS is required on every physical connection, including pool growth and
replacement. A server greeting without TLS support is rejected before sending
authentication data; snekql never retries that connection in plaintext.
`tls=None` retains the existing non-TLS behavior.

An isolated aiomysql pool adaptation owns partial connections on both paths and
adds a guarded handshake for required TLS. aiomysql 0.3.2 otherwise treats an SSL
context opportunistically and can leave a socket open on native cancellation.
The driver extra is constrained to `>=0.3.2,<0.4`; widening it requires rechecking
the handshake and pool-lifecycle tests. This adaptation does not change global
driver behavior. See the [driver audit](connection-lifecycle.md#driver-audit).

TLS is a TCP policy and cannot be combined with `unix_socket`. A failed trust or
hostname check prevents initialization.

### Connection recycling and health

```python
config = mariadb.Config(
    database="app",
    user="snekql",
    max_connection_lifetime=3600,
    max_connection_idle=300,
    health_check="checkout",
)
```

Both duration limits default to `None`, disabling age-based recycling. Enabled
limits must be finite positive seconds. Zero, negative values, infinity, NaN,
booleans, and numeric strings are rejected.

- `max_connection_lifetime` measures age since successful physical connection
  establishment, even when that connection is used frequently.
- `max_connection_idle` measures time since the last return to the pool. Time
  spent in an active Transaction does not count as idle time.
- The default `health_check="passive"` preserves aiomysql's detection of observed
  EOF and socket errors without adding a ping round trip.
- `health_check="checkout"` sends a ping before handing out each connection.
  Ping uses `reconnect=False`. A failed probe closes and discards the connection
  and fails acquisition. It does not silently retry that acquisition. A later
  Transaction may acquire a fresh connection.

Recycling runs only when acquiring a connection. There is no background reaper
or maximum Transaction duration. An expired connection is replaced before work
begins; an active Transaction is never interrupted to enforce an age limit.
Admission, replacement, health checking, and required session configuration
share the acquisition deadline. Very short lifetime limits can exhaust that
budget by repeatedly expiring newly opened connections.

New physical connections reapply and verify the required session settings.
Required TLS remains required on every replacement. These policies apply to
ordinary Transactions and other operations acquiring connections from the same
Database, including migrations. Health checks do not guarantee that a server
will remain available after checkout. A failure during an active Transaction
still fails closed; no statement or Transaction is automatically replayed.

SQLite has no automatic age-based recycling or checkout health policy. In
particular, replacing its sole in-memory connection would destroy its database.

### Minimum version

snekql verifies the server is MariaDB and at least **10.11**. Older MariaDB
builds and non-MariaDB servers such as MySQL are rejected at initialization.
The maintained LTS targets are 10.11, 11.4, 11.8 and 12.3. Admission does not
certify every intervening release or old patch. See the
[release/capability matrix](mariadb-support.md) for native validation, retained
unsupported-feature diagnostics and maintenance limits.

### Session settings (per connection)

| Setting | Value | Why |
| --- | --- | --- |
| `sql_mode` | includes `STRICT_ALL_TABLES`, `NO_ENGINE_SUBSTITUTION` | `STRICT_ALL_TABLES` is the runtime analogue of SQLite `STRICT` tables: invalid or out-of-range values are rejected, not silently coerced. `NO_ENGINE_SUBSTITUTION` turns a missing storage engine into an error instead of a silent swap. |
| `time_zone` | `+00:00` | Server-side `CURRENT_TIMESTAMP` defaults are generated in UTC to match snekql's UTC datetime codec. |
| `foreign_key_checks` | `1` | Keeps the emitted `FOREIGN KEY` constraints enforced. |
| `check_constraint_checks` | `1` | Keeps Migration History's position, name, and checksum checks enforced. |
| `unique_checks` | `1` | Keeps Migration History's byte-exact name uniqueness enforced. |

### InnoDB page size

snekql verifies that `innodb_page_size` is at least 8192 bytes. Migration
History stores migration names as up to 1020 UTF-8 bytes and uses a full unique
index so name identity stays byte-exact. MariaDB's 4 KiB InnoDB page format
cannot represent that index and is rejected at initialization instead of
failing later while the history table is created.

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
