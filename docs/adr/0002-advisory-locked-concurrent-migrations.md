# Advisory-locked concurrent migrations

snekql coordinates concurrent migration runs with a backend advisory lock so that
several instances calling `Database.initialize(migrations=...)` or
`Database.migrate(...)` at once are safe. This reverses the v1 "concurrent runs
are undefined; migrate from a single place" boundary recorded in
[ADR 0001](0001-hand-authored-raw-sql-migrations.md).

The migration runner holds a lock around the **entire** apply flow — ensure
history, read applied, run pending, record. The instance that wins the race
applies the pending migrations; losers block until it finishes, then re-read the
now-complete Migration History and apply only what is still pending. The lock is
**always on** whenever migrations are provided: it is one cheap round-trip and
removes a sharp-edged "caller's responsibility" with no ergonomic cost.

## Considered Options

- **MariaDB: `GET_LOCK` named advisory lock vs. a lock row in `snekql_migrations`.**
  Chose `GET_LOCK`: it is connection-scoped, so it releases automatically on a
  clean exit *and* on disconnect (a crashed instance frees it server-side), and it
  has built-in wait/timeout semantics. A lock *row* would need its own crash
  recovery (stale-lock detection, TTLs) — exactly the bookkeeping `GET_LOCK`
  removes. The lock name is namespaced per database (`snekql_migrations.<db>`,
  folded to a digest past the 64-char cap) because `GET_LOCK` names are
  server-wide, so unrelated apps on a shared server do not serialize each other.

- **SQLite: explicit coordination vs. file write-serialization.** Chose to lean on
  SQLite's single-writer file lock plus `busy_timeout`. SQLite has no advisory-lock
  primitive, and a held write transaction cannot wrap the migration bodies without
  violating ADR 0001's "snekql owns no transaction boundary" rule (bodies own their
  own transactions). Concurrent runs against one file therefore serialize their
  writes and a losing writer waits rather than erroring; the documented strong
  guarantee remains "migrate from a single place."

- **Opt-in flag vs. always-on locking.** Chose always-on. A flag adds a footgun
  (forgetting it reintroduces the race) for no benefit; the lock cost is negligible.

- **Wrap the whole run in one snekql transaction for atomicity.** Rejected: ADR
  0001 deliberately keeps bodies and bookkeeping non-atomic and migrations
  idempotent. The lock coordinates *who* runs, not *whether* a run is atomic.

## Consequences

- Concurrent `initialize(migrations=...)` against one MariaDB database applies each
  migration exactly once; losers observe the completed history instead of
  re-applying.
- A MariaDB loser that cannot acquire the lock within `acquire_timeout` raises the
  new public `MigrationLockTimeoutError` having applied nothing; a retry after the
  holder finishes resumes normally.
- The lock releases on success, failure, and disconnect, so a crash mid-migration
  does not strand the lock.
- SQLite coordination stays best-effort (write-serialization), so running
  migrations from a single place remains the recommendation there.
- `docs/migrations.md` documents the coordination model for both backends.
